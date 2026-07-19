"""Core coordinator for LLM Smart Assistant.

Handles state listening, LLM API communication, response parsing,
and triggering action execution.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_CALL_SERVICE,
    ACTION_CREATE_AUTOMATION,
    ACTION_GET_STATES,
    ACTION_TTS_SPEAK,
    ACTION_UPDATE_AUTOMATION_PROMPT,
    MAX_REASONING_ITERATIONS,
    REASONING_TIMEOUT,
    CONF_ALLOW_AUTOMATION,
    CONF_API_BASE_URL,
    CONF_API_KEY,
    CONF_DISABLED_AUTOMATIONS,
    CONF_DOMAINS_WHITELIST,
    CONF_ENTITIES_WHITELIST,
    CONF_HISTORY_COUNT,
    CONF_HISTORY_ENABLED,
    CONF_HISTORY_MODE,
    CONF_HISTORY_TIME_WINDOW,
    CONF_IGNORE_DUPLICATE,
    CONF_INPUT_ENTITIES,
    CONF_MAX_TOKENS,
    CONF_MODEL_NAME,
    CONF_PROMPT_AUTOMATION,
    CONF_PROMPT_DEFAULT,
    CONF_TEMPERATURE,
    CONF_TTS_CUSTOM_TEMPLATE,
    CONF_TTS_ENTITY_ID,
    CONF_TTS_MODE,
    CONF_TTS_SPEAK_VOLUME,
    CONF_TTS_MUTE_AFTER,
    CONF_TTS_MUTE_ENTITY_ID,
    DEFAULT_PROMPT_AUTOMATION,
    DEFAULT_PROMPT_DEFAULT,
    DEFAULT_TTS_SPEAK_VOLUME,
    DEFAULT_TTS_MUTE_AFTER,
    HARDCODED_AUTOMATION_PROMPT,
    HARDCODED_SYSTEM_PROMPT,
    DOMAIN,
    HISTORY_MODE_COUNT,
    HISTORY_MODE_TIME,
    STORAGE_KEY,
    STORAGE_VERSION,
    TTS_MODE_CUSTOM,
    TTS_MODE_STANDARD,
    TTS_MODE_XIAOMI_MIOT,
)

_LOGGER = logging.getLogger(__name__)


class LLMChatMessage:
    """Represents a single chat message in the conversation history."""

    def __init__(self, role: str, content: str, timestamp: datetime | None = None) -> None:
        self.role = role
        self.content = content
        self.timestamp = timestamp or dt_util.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMChatMessage":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


class DynamicAutomation:
    """Represents a dynamically created automation rule."""

    def __init__(
        self,
        automation_id: str,
        entity_id: str,
        condition: str,
        prompt: str,
        description: str = "",
    ) -> None:
        self.automation_id = automation_id
        self.entity_id = entity_id
        self.condition = condition
        self.prompt = prompt
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "automation_id": self.automation_id,
            "entity_id": self.entity_id,
            "condition": self.condition,
            "prompt": self.prompt,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DynamicAutomation":
        return cls(
            automation_id=data["automation_id"],
            entity_id=data["entity_id"],
            condition=data["condition"],
            prompt=data["prompt"],
            description=data.get("description", ""),
        )


class LLMSmartAssistantCoordinator:
    """Core coordinator that manages the LLM integration lifecycle.

    Responsibilities:
    - Listen to configured sensor state changes
    - Maintain conversation history with truncation
    - Send requests to LLM API
    - Parse LLM JSON responses
    - Execute actions via ServicesExecutor
    - Manage dynamic automations

    Also exposes the last response for UI display purposes.
    """

    last_response: dict[str, Any] | None = None
    last_response_raw: str = ""
    last_prompt_messages: list[dict[str, str]] = []
    in_progress: bool = False
    current_round: int = 0

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry_data: dict[str, Any],
        config_entry_options: dict[str, Any],
    ) -> None:
        self.hass = hass
        self._data = dict(config_entry_data)
        self._options = dict(config_entry_options)

        # Conversation history
        self._history: list[LLMChatMessage] = []

        # Registered state listeners (input sensors)
        self._state_listeners: list[callable] = []

        # Dynamic automations
        self._automations: dict[str, DynamicAutomation] = {}
        self._automation_listeners: dict[str, callable] = {}
        self._disabled_automations_set: set = set()

        # Storage for persistence
        self._store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )

        # Last processed state per entity (for duplicate detection)
        self._last_states: dict[str, str] = {}
        # Last trigger time per entity (for debounce)
        self._last_trigger_time: dict[str, float] = {}

        # Background tasks
        self._unload_tasks: list[asyncio.Task] = []

        # Flag to track if coordinator is started
        self._is_started = False

        # Reference to the executor (set externally after creation)
        self.executor = None

        # Listeners for sensor entity updates
        self._listeners: list[callable] = []
        # Debounce timer for storage saves
        self._save_timer = None

    # ------------------------------------------------------------------
    # Listener callbacks (for sensor entity updates)
    # ------------------------------------------------------------------

    @callback
    def async_add_listener(self, update_callback: callable) -> callable:
        """Register a callback for data updates. Returns a remove function."""
        self._listeners.append(update_callback)

        def _remove():
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove

    def _async_notify_listeners(self) -> None:
        """Notify all registered listeners of a data update."""
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                _LOGGER.exception("Error in coordinator listener callback")

    # ------------------------------------------------------------------
    # Config accessors
    # ------------------------------------------------------------------

    @property
    def api_base_url(self) -> str:
        return self._options.get(CONF_API_BASE_URL) or self._data.get(CONF_API_BASE_URL, "")

    @property
    def api_key(self) -> str:
        return self._options.get(CONF_API_KEY) or self._data.get(CONF_API_KEY, "")

    @property
    def model_name(self) -> str:
        return self._options.get(CONF_MODEL_NAME) or self._data.get(CONF_MODEL_NAME, "")

    @property
    def temperature(self) -> float:
        # Check data first, then options (allows OptionsFlow to work before sync)
        val = self._data.get(CONF_TEMPERATURE)
        if val is None:
            val = self._options.get(CONF_TEMPERATURE, 0.7)
        return float(val)

    @property
    def max_tokens(self) -> int:
        # Check data first, then options
        val = self._data.get(CONF_MAX_TOKENS)
        if val is None:
            val = self._options.get(CONF_MAX_TOKENS, 1024)
        return int(val)

    @property
    def prompt_default(self) -> str:
        """Full system prompt: hardcoded core + user customization.
        If the saved prompt already contains the hardcoded core (old format),
        use it as-is for backward compatibility."""
        user_part = self._options.get(CONF_PROMPT_DEFAULT, DEFAULT_PROMPT_DEFAULT)
        if HARDCODED_SYSTEM_PROMPT[:40] in user_part:
            return user_part
        return HARDCODED_SYSTEM_PROMPT + "\n" + user_part

    @property
    def prompt_automation(self) -> str:
        """Full automation prompt: hardcoded core + user customization.
        If the saved prompt already contains the hardcoded core (old format),
        use it as-is for backward compatibility."""
        user_part = self._options.get(CONF_PROMPT_AUTOMATION, DEFAULT_PROMPT_AUTOMATION)
        if HARDCODED_AUTOMATION_PROMPT[:40] in user_part:
            return user_part
        return HARDCODED_AUTOMATION_PROMPT + "\n" + user_part

    @property
    def input_entities(self) -> list[str]:
        return self._options.get(CONF_INPUT_ENTITIES, [])

    @property
    def ignore_duplicate(self) -> bool:
        return self._options.get(CONF_IGNORE_DUPLICATE, True)

    @property
    def tts_entity_id(self) -> str:
        return self._options.get(CONF_TTS_ENTITY_ID, "")

    @property
    def tts_mode(self) -> str:
        return self._options.get(CONF_TTS_MODE, TTS_MODE_STANDARD)

    @property
    def tts_speak_volume(self) -> float:
        return float(self._options.get(CONF_TTS_SPEAK_VOLUME, DEFAULT_TTS_SPEAK_VOLUME))

    @property
    def tts_mute_after(self) -> bool:
        return bool(self._options.get(CONF_TTS_MUTE_AFTER, DEFAULT_TTS_MUTE_AFTER))

    @property
    def tts_mute_entity_id(self) -> str:
        return self._options.get(CONF_TTS_MUTE_ENTITY_ID, "")

    @property
    def tts_custom_template(self) -> str:
        return self._options.get(CONF_TTS_CUSTOM_TEMPLATE, "")

    @property
    def domains_whitelist(self) -> list[str]:
        return self._options.get(CONF_DOMAINS_WHITELIST, ["light", "switch", "media_player", "sensor", "input_boolean"])

    @property
    def entities_whitelist(self) -> list[str]:
        return self._options.get(CONF_ENTITIES_WHITELIST, [])

    @property
    def history_enabled(self) -> bool:
        return self._options.get(CONF_HISTORY_ENABLED, True)

    @property
    def history_mode(self) -> str:
        return self._options.get(CONF_HISTORY_MODE, HISTORY_MODE_COUNT)

    @property
    def history_count(self) -> int:
        return int(self._options.get(CONF_HISTORY_COUNT, 10))

    @property
    def history_time_window(self) -> int:
        return int(self._options.get(CONF_HISTORY_TIME_WINDOW, 60))

    @property
    def disabled_automations(self) -> list:
        return self._options.get(CONF_DISABLED_AUTOMATIONS, [])

    def _get_disabled_automations(self):
        return list(self._disabled_automations_set)

    @property
    def allow_automation(self) -> bool:
        return self._options.get(CONF_ALLOW_AUTOMATION, True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Start the coordinator: load storage, register listeners."""
        if self._is_started:
            return
        self._is_started = True

        # Load persisted data
        await self._async_load_storage()

        # Register state listeners for input entities
        await self._async_register_listeners()

        # Register automation listeners
        await self._async_register_automation_listeners()

        _LOGGER.info(
            "LLM Smart Assistant coordinator started. Monitoring: %s",
            self.input_entities,
        )

    async def async_unload(self) -> None:
        """Unload the coordinator: remove listeners, save storage."""
        self._is_started = False

        # Remove state listeners
        for remove_listener in self._state_listeners:
            remove_listener()
        self._state_listeners.clear()

        # Remove automation listeners
        for remove_listener in self._automation_listeners.values():
            remove_listener()
        self._automation_listeners.clear()

        # Cancel background tasks (use copy to avoid modification during iteration)
        for task in list(self._unload_tasks):
            task.cancel()
        self._unload_tasks.clear()

        # Save storage
        await self._async_save_storage()

        _LOGGER.info("LLM Smart Assistant coordinator unloaded.")

    async def async_update_config(
        self, new_data: dict[str, Any] | None = None,
        new_options: dict[str, Any] | None = None,
    ) -> None:
        """Update configuration at runtime and re-register listeners if needed."""
        if new_data:
            self._data.update(new_data)
        if new_options:
            self._options.update(new_options)

        # Re-register listeners if input entities changed
        for remove_listener in self._state_listeners:
            remove_listener()
        self._state_listeners.clear()

        await self._async_register_listeners()

    # ------------------------------------------------------------------
    # State listeners for input sensors
    # ------------------------------------------------------------------

    async def _async_register_listeners(self) -> None:
        """Register state change listeners for each configured input entity."""
        for entity_id in self.input_entities:
            remove_listener = async_track_state_change_event(
                self.hass,
                entity_id,
                self._async_handle_sensor_change,
            )
            self._state_listeners.append(remove_listener)
            _LOGGER.debug("Registered listener for entity: %s", entity_id)

    @callback
    def _async_handle_sensor_change(self, event: Event) -> None:
        """Handle a sensor state change event."""
        if not self._is_started:
            return

        entity_id = event.data.get("entity_id", "")
        new_state: State | None = event.data.get("new_state")

        if new_state is None:
            return

        state_text = str(new_state.state).strip()

        # Skip empty/unavailable states
        if not state_text or state_text in ("", "unavailable", "unknown", "none"):
            return

        # Duplicate detection (handles Xiaomi MIoT phantom updates with same content)
        if self.ignore_duplicate:
            last_state = self._last_states.get(entity_id)
            if last_state == state_text:
                _LOGGER.debug("Ignoring duplicate input from %s (same text)", entity_id)
                return
            # Also check if the previous state text is a substring of the new one
            # (Xiaomi sometimes appends timestamps or other noise)
            if last_state and state_text.startswith(last_state) and len(state_text) > len(last_state) + 5:
                _LOGGER.debug("Ignoring appended noise from %s: '%s' -> '%s'", entity_id, last_state, state_text)
                return

        self._last_states[entity_id] = state_text

        # Process the input asynchronously
        task = self.hass.async_create_task(
            self._async_process_user_input(entity_id, state_text),
            name=f"{DOMAIN}_process_input_{entity_id}",
        )
        self._unload_tasks.append(task)
        def _safe_remove(t):
            try:
                self._unload_tasks.remove(t)
            except ValueError:
                pass
        task.add_done_callback(_safe_remove)

    # ------------------------------------------------------------------
    # LLM API communication
    # ------------------------------------------------------------------

    def _build_system_context(self, prompt_template: str, **kwargs: Any) -> str:
        """Build the system prompt by injecting context variables."""
        # Gather HA context
        now = dt_util.now()
        exposed_entities = self._get_exposed_entities_info()

        context = {
            "time": now.strftime("%H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "exposed_entities": exposed_entities,
            **kwargs,
        }

        # Simple template substitution
        prompt = prompt_template
        for key, value in context.items():
            placeholder = "{{ " + key + " }}"
            prompt = prompt.replace(placeholder, str(value))

        return prompt

    def _get_exposed_entities_info(self) -> str:
        """Get a CSV-formatted list of exposed/whitelisted entities."""
        return self._build_entity_csv()

    def _build_entity_csv(self) -> str:
        """Build a compact CSV of available entities for LLM context.

        Format: entity_id, friendly_name, state, area
        This is compact, easy for LLMs to parse, and includes only
        whitelisted entities in non-error states.
        """
        lines = ["entity_id,name,state,area"]
        domains = self.domains_whitelist
        entity_ids = self.entities_whitelist

        for state_obj in self.hass.states.async_all():
            entity_id = state_obj.entity_id
            domain = entity_id.split(".")[0]

            # Skip unavailable/unknown
            if state_obj.state in ("unknown", "unavailable", "none"):
                continue

            # Check whitelist
            if entity_ids and entity_id not in entity_ids:
                continue
            if domains and domain not in domains:
                continue

            attrs = state_obj.attributes
            friendly = attrs.get("friendly_name", entity_id).replace(",", " ")
            state_val = state_obj.state.replace(",", " ")
            area = self._get_area_name(entity_id)

            lines.append(f"{entity_id},{friendly},{state_val},{area}")

        return "\n".join(lines)

    @staticmethod
    def _get_area_name(entity_id: str) -> str:
        """Get the area name for an entity, if available."""
        # Area lookup requires registry access; return empty for now
        # HA stores area in entity registry, accessible via:
        # hass.data['entity_registry'].async_get(entity_id)?.area_id
        return ""

    async def _async_query_llm_raw(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
    ) -> str | None:
        """Send a chat completion and return raw text content (no JSON parsing)."""
        url = f"{self.api_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content", "")
            return content.strip() or None
        except Exception:
            return None

    async def _async_query_llm(
        self,
        messages: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        """Send a chat completion request to the LLM API with retry.

        Retries up to 2 times with exponential backoff (1s, 3s) on transient errors.
        Returns the parsed JSON response, or None on failure.
        """
        url = f"{self.api_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        # Force JSON output format - required for reliable parsing
        # Supported by OpenAI, DeepSeek, and most compatible APIs
        payload["response_format"] = {"type": "json_object"}

        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                wait = 1 * (3 ** (attempt - 1))  # 1s, 3s
                _LOGGER.info("LLM API retry %d/%d after %.1fs", attempt, max_retries, wait)
                await asyncio.sleep(wait)

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 429:
                            last_error = f"Rate limited (429), attempt {attempt + 1}"
                            _LOGGER.warning(last_error)
                            continue
                        if resp.status >= 500:
                            last_error = f"Server error ({resp.status}), attempt {attempt + 1}"
                            _LOGGER.warning(last_error)
                            continue
                        if resp.status != 200:
                            error_text = await resp.text()
                            _LOGGER.error(
                                "LLM API error (status %s): %s",
                                resp.status,
                                error_text,
                            )
                            return None

                        data = await resp.json()

                # Extract the assistant's message
                choices = data.get("choices", [])
                if not choices:
                    _LOGGER.error("LLM returned no choices: %s", data)
                    return None

                message = choices[0].get("message", {})
                content = message.get("content", "")

                if not content:
                    _LOGGER.warning("LLM returned empty content, retrying (%d/%d)", attempt + 1, max_retries + 1)
                    last_error = "Empty content"
                    continue

                _LOGGER.info("LLM raw response received (%d chars)", len(content))

                # Try to parse as JSON (handle extra text after JSON)
                parsed = None
                content_stripped = content.strip()
                # First try direct parse
                try:
                    parsed = json.loads(content_stripped)
                except json.JSONDecodeError:
                    # Try to find JSON object by scanning for first { and last }
                    start = content_stripped.find('{')
                    end = content_stripped.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        try:
                            parsed = json.loads(content_stripped[start:end+1])
                        except json.JSONDecodeError:
                            pass

                if parsed is None:
                    _LOGGER.error(
                        "Failed to parse LLM response as JSON (attempt %d/%d)\nRaw: %s",
                        attempt + 1, max_retries + 1, content[:500],
                    )
                    last_error = "JSON parse failed"
                    continue

                if not isinstance(parsed, dict):
                    _LOGGER.error("LLM response is not a JSON object (attempt %d/%d): %s",
                        attempt + 1, max_retries + 1, str(parsed)[:200])
                    last_error = "Not a JSON object"
                    continue

                _LOGGER.info("LLM JSON parsed: tts_text='%s', steps=%s",
                    str(parsed.get("tts_text",""))[:100],
                    str(parsed.get("steps",[]))[:200])
                return parsed

            except asyncio.TimeoutError:
                last_error = f"Timeout, attempt {attempt + 1}"
                _LOGGER.warning(last_error)
            except aiohttp.ClientError as exc:
                last_error = f"Connection error: {exc}, attempt {attempt + 1}"
                _LOGGER.warning(last_error)
            except Exception as exc:
                _LOGGER.error("Unexpected LLM API error: %s", exc)
                return None

        _LOGGER.error("LLM API request failed after %d retries: %s", max_retries, last_error)
        # Return a fallback response so the user gets a graceful message
        return {
            "tts_text": "",
            "steps": [],
        }

    # ------------------------------------------------------------------
    # Conversation history management
    # ------------------------------------------------------------------

    def _add_to_history(self, message: LLMChatMessage) -> None:
        """Add a message to history, apply truncation, and persist."""
        self._history.append(message)
        self._truncate_history()
        _LOGGER.info("History now has %d messages", len(self._history))
        # Schedule debounced save (2s delay, cancels previous pending save)
        self._schedule_storage_save()

    def _schedule_storage_save(self) -> None:
        """Save storage after a debounce delay to avoid I/O storms."""
        # Cancel previous pending save
        if self._save_timer is not None:
            self._save_timer.cancel()
        # Schedule a new save in 2 seconds
        self._save_timer = self.hass.loop.call_later(
            2.0,
            lambda: self.hass.async_create_task(self._async_save_storage())
        )

    def _truncate_history(self) -> None:
        """Truncate history: apply BOTH count AND time constraints."""
        if not self.history_enabled:
            self._history = self._history[-1:]  # keep only current turn
            return
        # Always apply count constraint
        max_count = max(self.history_count, 1)
        if len(self._history) > max_count:
            self._history = self._history[-max_count:]
        # Always apply time constraint
        window_minutes = max(self.history_time_window, 1)
        cutoff = dt_util.utcnow() - timedelta(minutes=window_minutes)
        self._history = [m for m in self._history if m.timestamp >= cutoff]

    def _build_messages_for_llm(
        self,
        user_input: str,
        prompt_template: str | None = None,
        extra_system_context: str | None = None,
        **context_kwargs: Any,
    ) -> list[dict[str, str]]:
        """Build the messages array for the LLM API call.

        Includes system prompt, history (if any), and the current user input.
        """
        messages: list[dict[str, str]] = []

        # System prompt
        template = prompt_template or self.prompt_default
        system_content = self._build_system_context(template, **context_kwargs)
        if extra_system_context:
            system_content += "\n\n" + extra_system_context
        messages.append({"role": "system", "content": system_content})

        # Conversation history (skip system, only user/assistant)
        for hist_msg in self._history:
            messages.append({
                "role": hist_msg.role,
                "content": hist_msg.content,
            })

        # Current user input
        messages.append({"role": "user", "content": user_input})

        return messages

    # ------------------------------------------------------------------
    # Main processing pipeline
    # ------------------------------------------------------------------

    async def _async_process_user_input(
        self, entity_id: str, user_text: str
    ) -> None:
        """Process a user input through multi-step reasoning loop.

        Each round:
        1. Call LLM → get response with steps
        2. Execute steps (call_service, get_states, etc.)
        3. If there were observations (get_states results), feed them back to LLM
        4. Continue until task is complete or timeout/iteration limit
        """
        _LOGGER.info(
            "Processing input from %s: %s",
            entity_id,
            user_text[:100],
        )

        start_time = asyncio.get_running_loop().time()
        max_iterations = MAX_REASONING_ITERATIONS
        timeout = REASONING_TIMEOUT

        # Add user message to history
        self._add_to_history(LLMChatMessage(role="user", content=user_text))

        # Expose entities list for system context
        exposed = self._build_exposed_entities_list()

        # Set in_progress flag for sensor updates
        self.in_progress = True
        self.current_round = 0

        # Multi-step reasoning loop
        iteration = 0
        cumulative_tts = []
        all_steps_ever = []
        all_rounds = []  # Track each round for debug display
        current_messages = self._build_messages_for_llm(
            user_text,
            max_iterations=max_iterations,
            timeout=timeout,
            exposed_entities=exposed,
        )
        # Store for debug display
        self.last_prompt_messages = current_messages

        while iteration < max_iterations:
            iteration += 1
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed > timeout:
                _LOGGER.warning(
                    "Reasoning loop timed out after %.1fs (%d iterations)",
                    elapsed, iteration
                )
                cumulative_tts.append("Sorry, the request timed out.")
                break

            _LOGGER.info(
                "--- Reasoning round %d/%d (elapsed %.1fs) ---",
                iteration, max_iterations, elapsed
            )

            # Call LLM
            response = await self._async_query_llm(current_messages)

            if response is None:
                _LOGGER.error("LLM returned None on round %d", iteration)
                cumulative_tts.append(
                    "Sorry, I encountered an error processing your request."
                )
                break

            # Update current round and notify sensor entities
            self.current_round = iteration
            self.last_response = response
            self.last_response_raw = json.dumps(response, ensure_ascii=False, indent=2)
            self._async_notify_listeners()

            # Extract tts_text and steps
            tts_text = response.get("tts_text", "")
            steps = response.get("steps", [])

            _LOGGER.info(
                "Round %d: tts_text='%s', steps=%s",
                iteration, str(tts_text)[:100], str(steps)[:200]
            )

            # Accumulate TTS only when task is fully complete (no more steps)
            # If LLM speaks but still has actions, delay the speech to final round
            if tts_text and not steps:
                cumulative_tts.append(tts_text)

            # Track each round for debug
            all_rounds.append({
                "round": iteration,
                "tts_text": tts_text,
                "steps": steps,
            })

            # If no steps, we're done
            if not steps:
                _LOGGER.info(
                    "No steps returned, reasoning complete after %d rounds",
                    iteration
                )
                break

            all_steps_ever.extend(steps)

            # Execute steps and collect results for feedback
            step_feedback = []
            if self.executor:
                step_results = await self.executor.async_execute_steps(steps)
                for result in step_results:
                    action = result.get("action", "unknown")
                    success = result.get("success", False)
                    step_result_data = result.get("result", {})

                    if action == ACTION_GET_STATES:
                        # get_states: feed back observed states
                        obs = step_result_data.get("observed", [])
                        for o in obs:
                            ent_id = o.get("entity_id", "?")
                            ent_state = o.get("state", "unknown")
                            friendly = o.get("attributes", {}).get("friendly_name", "")
                            unit = o.get("attributes", {}).get("unit_of_measurement", "")
                            label = f"{friendly} ({ent_id})" if friendly else ent_id
                            val = f"{ent_state} {unit}" if unit else str(ent_state)
                            step_feedback.append(f"  - {label}: {val}")

                    elif action == ACTION_CALL_SERVICE:
                        # call_service: feed back execution result
                        domain = step_result_data.get("domain", "?")
                        service = step_result_data.get("service", "?")
                        target = step_result_data.get("target", {})
                        entity_target = target.get("entity_id", "unknown") if target else "unknown"
                        if success:
                            # Check the new state after service call
                            new_state = self.hass.states.get(entity_target)
                            new_val = new_state.state if new_state else "?"
                            step_feedback.append(
                                f"  - Executed {domain}.{service} on {entity_target}"
                                f" → new state: {new_val}"
                            )
                        else:
                            error = result.get("error", "Unknown error")
                            step_feedback.append(f"  - Failed {domain}.{service} on {entity_target}: {error}")

                    elif action == ACTION_CREATE_AUTOMATION:
                        # create_automation: feed back the automation id so LLM knows it's done
                        auto_id = step_result_data.get("automation_id", "")
                        entity = step_result_data.get("entity_id", "")
                        cond = step_result_data.get("condition", "")
                        if success and auto_id:
                            step_feedback.append(
                                f"  - create_automation: DONE (id={auto_id[:8]}, entity={entity}, condition={cond})"
                            )
                        elif not success:
                            error = result.get("error", "Unknown error")
                            step_feedback.append(f"  - create_automation: failed ({error})")
                    elif success:
                        step_feedback.append(f"  - {action}: completed")
                    else:
                        error = result.get("error", "Unknown error")
                        step_feedback.append(f"  - {action}: failed ({error})")

            # If there's any feedback, feed it back to the LLM
            if step_feedback:
                feedback_text = "步骤执行结果:\n" + "\n".join(step_feedback)
                _LOGGER.debug("Step feedback:\n%s", feedback_text)

                # Add as a user message to continue reasoning
                current_messages.append({
                    "role": "user",
                    "content": feedback_text,
                })
                # Continue to the next round
            else:
                # No feedback means no steps were executed
                _LOGGER.info(
                    "No step feedback, reasoning complete after %d rounds",
                    iteration
                )
                break

        # Build final response text
        final_tts = " ".join(cumulative_tts) if cumulative_tts else ""

        # If LLM gave no tts_text but there are steps, generate a default summary
        if not final_tts and all_steps_ever:
            service_steps = [s for s in all_steps_ever if s.get("action") == "call_service"]
            if service_steps:
                final_tts = f"Done. Executed {len(service_steps)} action(s)."
            else:
                final_tts = "Done."
        elif not final_tts and iteration > 1:
            final_tts = "Done."

        # Speak TTS
        if final_tts:
            await self._async_speak_tts(final_tts)

        # Add only the FINAL assistant response to history (not intermediate rounds)
        self._add_to_history(
            LLMChatMessage(
                role="assistant",
                content=final_tts,
            )
        )

        # Update last_response with aggregated data for UI display
        self.last_response = {
            "tts_text": final_tts,
            "steps": all_steps_ever,
            "iterations": iteration,
            "rounds": all_rounds,  # All rounds for debug
        }
        self.last_response_raw = json.dumps(
            self.last_response, ensure_ascii=False, indent=2
        )

        # Set in_progress to false and notify sensor entities
        self.in_progress = False
        self.current_round = iteration
        self._async_notify_listeners()

        _LOGGER.info(
            "Reasoning completed: %d rounds, %d total steps, tts='%s'",
            iteration, len(all_steps_ever), final_tts[:100]
        )

    def _build_exposed_entities_list(self) -> str:
        """Build a summary of available entities for the system prompt."""
        lines = []
        for state_obj in self.hass.states.async_all():
            domain = state_obj.domain
            allowed = self.domains_whitelist
            if allowed and domain not in allowed:
                continue
            friendly = state_obj.attributes.get("friendly_name", state_obj.entity_id)
            lines.append(f"  - {state_obj.entity_id} ({friendly}): {state_obj.state}")
        return "\n".join(lines[:500])

    async def _async_process_automation_trigger(
        self, automation: DynamicAutomation, state: State
    ) -> None:
        """Process a dynamic automation trigger via LLM.
        
        Passes the full available entities list to the LLM so it can
        determine the correct action and entity IDs dynamically.
        """
        _LOGGER.info(
            "Automation '%s' triggered by %s = %s",
            automation.automation_id,
            automation.entity_id,
            state.state,
        )

        # Build entity context (CSV format, compact and LLM-friendly)
        # Build rich device list with area info from registry
        entity_context = "Available Devices (entity_id,domain,name,state,unit,extra):\n" + self._build_entity_csv()
        
        action_prompt = automation.prompt or automation.description or "Execute the configured automation action"
        
        # Determine language from HA user config
        ha_lang = (self.hass.config.language or "en").split("-")[0]
        lang_names = {"zh": "Chinese", "en": "English", "ja": "Japanese", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese", "ko": "Korean", "ru": "Russian"}
        lang_name = lang_names.get(ha_lang, "English")

        messages = self._build_messages_for_llm(
            user_input=(
                f"AUTOMATION TRIGGERED\n"
                f"Trigger: {automation.entity_id} = {state.state}\n"
                f"Task: {action_prompt}\n"
                f"Language: {lang_name}\n"
                f"\n{entity_context}\n\n"
                f"IMPORTANT: Use ONLY the entity_ids listed above. Do NOT make up entities.\n"
                f"For example, if you see input_boolean.air_conditioner, use that (not climate.ac)."
            ),
            prompt_template=self.prompt_automation,
        )

        # Store for debug display
        self.last_prompt_messages = messages
        # Call LLM
        response = await self._async_query_llm(messages)

        if response is None:
            _LOGGER.error(
                "Automation '%s' LLM call failed", automation.automation_id
            )
            return

        tts_text = response.get("tts_text", "")
        steps = response.get("steps", [])

        # If LLM returned empty steps, try fallback matching
        if not steps:
            _LOGGER.info("LLM returned empty steps, trying fallback entity match")
            steps = self._try_fallback_automation_action(automation)
            if steps:
                _LOGGER.info("Fallback matched: %s", steps)

        # Execute steps
        if steps and self.executor:
            await self.executor.async_execute_steps(steps)

        # Speak TTS if text is present
        if tts_text:
            await self._async_speak_tts(tts_text)

    # ------------------------------------------------------------------
    # Dynamic Automation Management
    # ------------------------------------------------------------------

    async def async_create_automation(
        self,
        entity_id: str,
        condition: str,
        prompt: str,
        description: str = "",
    ) -> str | None:
        """Create a dynamic automation that listens for state changes.

        Returns the automation_id on success, or None on failure.
        """
        automation_id = str(uuid.uuid4())

        automation = DynamicAutomation(
            automation_id=automation_id,
            entity_id=entity_id,
            condition=condition,
            prompt=prompt,
            description=description,
        )

        # Register the listener
        try:
            remove_listener = async_track_state_change_event(
                self.hass,
                entity_id,
                lambda event: self._async_handle_automation_event(
                    automation, event
                ),
            )
            self._automation_listeners[automation_id] = remove_listener
            self._automations[automation_id] = automation

            # Persist to storage
            await self._async_save_storage()

            _LOGGER.info(
                "Created dynamic automation '%s': %s %s -> %s",
                automation_id,
                entity_id,
                condition,
                description,
            )

            return automation_id

        except Exception as exc:
            _LOGGER.error("Failed to create automation: %s", exc)
            return None

    async def async_remove_automation(self, automation_id: str) -> bool:
        """Remove a dynamic automation."""
        if automation_id not in self._automations:
            return False

        # Remove listener
        self._unregister_automation_listener(automation_id)
        self._disabled_automations_set.discard(automation_id)

        # Remove from dict
        self._automations.pop(automation_id, None)

        # Persist
        await self._async_save_storage()

        _LOGGER.info("Removed dynamic automation '%s'", automation_id)
        return True

    def _register_automation_listener(self, automation: "DynamicAutomation") -> None:
        """Register the state change listener for an automation."""
        from homeassistant.helpers.event import async_track_state_change_event
        remove_listener = async_track_state_change_event(
            self.hass,
            automation.entity_id,
            lambda event: self._async_handle_automation_event(automation, event),
        )
        self._automation_listeners[automation.automation_id] = remove_listener

    def _unregister_automation_listener(self, automation_id: str) -> None:
        """Unregister the state change listener for an automation."""
        remove_listener = self._automation_listeners.pop(automation_id, None)
        if remove_listener:
            remove_listener()

    async def async_disable_automation(self, automation_id: str) -> bool:
        """Disable an automation by removing its listener."""
        if automation_id not in self._automations:
            return False
        self._unregister_automation_listener(automation_id)
        self._disabled_automations_set.add(automation_id)
        await self._async_save_storage()
        _LOGGER.info("Disabled automation '%s' (listener removed)", automation_id)
        return True

    async def async_enable_automation(self, automation_id: str) -> bool:
        """Enable an automation by re-registering its listener."""
        if automation_id not in self._automations:
            return False
        automation = self._automations[automation_id]
        self._register_automation_listener(automation)
        self._disabled_automations_set.discard(automation_id)
        await self._async_save_storage()
        _LOGGER.info("Enabled automation '%s' (listener re-registered)", automation_id)
        return True

    async def _async_register_automation_listeners(self) -> None:
        """Re-register all persisted automation listeners."""
        # Clean up old listeners first (prevent duplicate registration)
        old_listeners = list(self._automation_listeners.values())
        for remove_fn in old_listeners:
            remove_fn()
        self._automation_listeners.clear()

        for automation in self._automations.values():
            remove_listener = async_track_state_change_event(
                self.hass,
                automation.entity_id,
                lambda event, a=automation: self._async_handle_automation_event(
                    a, event
                ),
            )
            self._automation_listeners[automation.automation_id] = remove_listener

    @callback
    def _async_handle_automation_event(
        self, automation: DynamicAutomation, event: Event
    ) -> None:
        """Handle a state change event for an automation."""
        if not self._is_started:
            return

        # Check if this automation is disabled
        if automation.automation_id in self.disabled_automations:
            _LOGGER.debug("Automation '%s' is disabled, skipping", automation.automation_id[:8])
            return

        new_state: State | None = event.data.get("new_state")
        old_state: State | None = event.data.get("old_state")

        if new_state is None or old_state is None:
            return

        # Evaluate the condition
        if not self._evaluate_condition(
            str(new_state.state), automation.condition
        ):
            return

        # Process the automation trigger (use add_job for thread-safety)
        self.hass.add_job(
            self._async_process_automation_trigger(automation, new_state)
        )

    @staticmethod
    def _evaluate_condition(state: str, condition: str) -> bool:
        """Evaluate a simple condition string against a state value.

        Supports: >, <, >=, <=, ==, != operators.
        Example conditions: ">30", "==on", "!=off", ">=20.5"
        """
        condition = condition.strip()

        # Try to parse numeric comparison
        for op in [">=", "<=", "!=", "==", ">", "<"]:
            if condition.startswith(op):
                rhs = condition[len(op):].strip()

                # Try numeric comparison
                try:
                    state_val = float(state)
                    cond_val = float(rhs)
                except (ValueError, TypeError):
                    # String comparison
                    state_val = state
                    cond_val = rhs

                if op == ">":
                    return state_val > cond_val
                if op == "<":
                    return state_val < cond_val
                if op == ">=":
                    return state_val >= cond_val
                if op == "<=":
                    return state_val <= cond_val
                if op == "==":
                    return state_val == cond_val
                if op == "!=":
                    return state_val != cond_val

        # If no operator found, treat as equality
        return state == condition

    # ------------------------------------------------------------------
    # TTS (Text-to-Speech)
    # ------------------------------------------------------------------

    def _try_fallback_automation_action(self, automation: DynamicAutomation) -> list[dict]:
        """Fallback: match automation prompt to entity names and generate steps."""
        action_prompt = (automation.prompt or automation.description or "").lower()
        all_states = self.hass.states.async_all()
        
        for s_obj in all_states:
            domain = s_obj.domain
            if self.domains_whitelist and domain not in self.domains_whitelist:
                continue
            friendly = s_obj.attributes.get("friendly_name", "").lower()
            eid_tail = s_obj.entity_id.split(".")[-1].replace("_", " ")
            
            # Check if entity name appears in the action prompt
            if (eid_tail in action_prompt or friendly in action_prompt):
                # Determine service from keywords in prompt
                if any(w in action_prompt for w in ["turn on", "打开", "开启", "open"]):
                    return [{"action": "call_service", "domain": domain,
                             "service": "turn_on", 
                             "target": {"entity_id": s_obj.entity_id}}]
                if any(w in action_prompt for w in ["turn off", "关闭", "关掉", "close", "停止"]):
                    return [{"action": "call_service", "domain": domain,
                             "service": "turn_off",
                             "target": {"entity_id": s_obj.entity_id}}]
        return []

    async def _async_speak_tts(self, text: str) -> None:
        """Speak text via the configured TTS mechanism.
        Tries to prevent speaker self-triggering (抢答) via:
        1. User-configured mute entity (media_player for volume control)
        2. Auto-detected DND switch
        3. Auto-detected sleep mode switch (fallback)
        """
        if not text or not self.tts_entity_id:
            return

        tts_entity = self.tts_entity_id
        media_domain = tts_entity.split(".")[0]

        # Determine which entity to use for muting:
        # 1. User-specified mute entity (e.g. a media_player that supports volume_set)
        # 2. Auto-detect DND switch (xiaomi_miot)
        # 3. Auto-detect sleep mode switch (xiaomi_miot fallback)
        _mute_switches = []
        if media_domain == "media_player":
            mute_entity = self.tts_mute_entity_id
            if mute_entity and self.hass.states.get(mute_entity):
                _mute_switches.append(("media_player", "volume_set",
                    {"entity_id": mute_entity, "volume_level": 0.0}))
                _mute_switches.append(("media_player", "volume_mute",
                    {"entity_id": mute_entity, "is_volume_muted": True}))
            else:
                # Auto-detect DND or sleep mode switches
                for suffix in ["no_disturb", "sleep_mode"]:
                    sw_id = tts_entity.replace("play_control", suffix).replace("media_player", "switch")
                    if self.hass.states.get(sw_id):
                        _mute_switches.append(("switch", "turn_on", {"entity_id": sw_id}))
                        break

        try:
            # ── Pre-TTS: disable mute so speaker can speak ──
            if _mute_switches:
                first = _mute_switches[0]
                if first[0] == "media_player":
                    # Unmute and set volume for speaking
                    await self.hass.services.async_call(
                        first[0], "volume_mute",
                        {"entity_id": first[1]["entity_id"], "is_volume_muted": False},
                        blocking=True,
                    )
                    await self.hass.services.async_call(
                        first[0], "volume_set",
                        {"entity_id": first[1]["entity_id"], "volume_level": self.tts_speak_volume},
                        blocking=True,
                    )
                else:
                    # Turn off DND/sleep switch
                    await self.hass.services.async_call(
                        "switch", "turn_off",
                        {"entity_id": first[2]["entity_id"]},
                        blocking=True,
                    )
                    await asyncio.sleep(0.5)

            # ── Speak ──
            if self.tts_mode == TTS_MODE_STANDARD:
                if media_domain == "tts":
                    await self.hass.services.async_call(
                        "tts", "speak",
                        {"entity_id": tts_entity, "message": text},
                        blocking=True,
                    )
                else:
                    await self.hass.services.async_call(
                        "media_player", "play_media",
                        {
                            "entity_id": tts_entity,
                            "media_content_id": text,
                            "media_content_type": "provider",
                        },
                        blocking=True,
                    )

            elif self.tts_mode == TTS_MODE_XIAOMI_MIOT:
                await self.hass.services.async_call(
                    "xiaomi_miot", "intelligent_speaker",
                    {
                        "entity_id": tts_entity,
                        "text": text,
                        "execute": False,
                        "silent": False,
                    },
                    blocking=True,
                )

            elif self.tts_mode == TTS_MODE_CUSTOM:
                if self.tts_custom_template:
                    from homeassistant.helpers.template import Template
                    tpl = Template(self.tts_custom_template, self.hass)
                    rendered = tpl.async_render({"tts_text": text})
                    _LOGGER.debug("Custom TTS rendered: %s", rendered)
                    try:
                        service_call = json.loads(rendered)
                        if isinstance(service_call, dict):
                            svc_domain = service_call.get("domain", "")
                            svc_service = service_call.get("service", "")
                            svc_data = service_call.get("data", {})
                            if svc_domain and svc_service:
                                await self.hass.services.async_call(
                                    svc_domain, svc_service, svc_data,
                                    blocking=True,
                                )
                                _LOGGER.debug("Custom TTS executed: %s.%s", svc_domain, svc_service)
                    except (json.JSONDecodeError, Exception) as exc:
                        _LOGGER.error("Custom TTS template did not produce valid service call JSON: %s", exc)

            _LOGGER.info("TTS spoken to %s: %s", tts_entity, text[:100])

            # ── Post-TTS: wait estimated duration, then re-mute ──
            if _mute_switches and self.tts_mute_after:
                # Estimate speech duration: ~5 chars/sec + per-pause + base
                clean = text.replace(" ", "").replace("\n", "")
                char_count = len(clean)
                pause_count = text.count(",") + text.count("。") + text.count("!") + text.count("?") + text.count(";")
                delay_ms = max(1000, char_count * 200 + pause_count * 300 + 500)
                _LOGGER.debug("TTS mute delay: %d ms for %d chars", delay_ms, char_count)
                await asyncio.sleep(delay_ms / 1000)
                for action in _mute_switches:
                    await self.hass.services.async_call(
                        action[0], action[1], action[2],
                        blocking=True,
                    )

        except Exception as exc:
            _LOGGER.error("TTS failed for %s: %s", tts_entity, exc)

    # ------------------------------------------------------------------
    # Storage (Persistence)
    # ------------------------------------------------------------------

    async def _async_load_storage(self) -> None:
        """Load persisted data (dynamic automations) from .storage."""
        stored = await self._store.async_load()
        if stored is None:
            return

        automations_data = stored.get("automations", [])
        for auto_data in automations_data:
            try:
                automation = DynamicAutomation.from_dict(auto_data)
                self._automations[automation.automation_id] = automation
            except Exception as exc:
                _LOGGER.error("Failed to load automation: %s", exc)

        _LOGGER.info(
            "Loaded %d dynamic automations from storage",
            len(self._automations),
        )

        # Also restore conversation history (most recent messages)
        history_data = stored.get("history", [])
        for msg_data in history_data:
            try:
                self._history.append(LLMChatMessage.from_dict(msg_data))
            except Exception as exc:
                _LOGGER.error("Failed to restore history message: %s", exc)
        if history_data:
            _LOGGER.info("Restored %d conversation history messages", len(history_data))

    async def _async_save_storage(self) -> None:
        """Save dynamic automations and conversation history to .storage."""
        history_data = [msg.to_dict() for msg in self._history[-50:]]
        data = {
            "automations": [
                auto.to_dict() for auto in self._automations.values()
            ],
            "history": history_data,
        }
        _LOGGER.info("Saving storage: %d automations, %d history messages",
                     len(data["automations"]), len(history_data))
        await self._store.async_save(data)
