"""Core coordinator for LLM Smart Assistant.

Handles state listening, LLM API communication, response parsing,
and triggering action execution.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACCESS_TOKEN,
    ACTION_CALL_SERVICE,
    ACTION_CREATE_AUTOMATION,
    ACTION_GET_STATES,
    ACTION_INSPECT,
    ACTION_TTS_SPEAK,
    ACTION_UPDATE_AUTOMATION_PROMPT,
    MAX_REASONING_ITERATIONS,
    REASONING_TIMEOUT,
    CONF_ALLOW_AUTOMATION,
    CONF_API_BASE_URL,
    CONF_API_KEY,
    CONF_DISABLED_AUTOMATIONS,
    CONF_DISABLE_THINKING,
    CONF_DOMAINS_WHITELIST,
    CONF_ENTITIES_WHITELIST,
    CONF_HISTORY_COUNT,
    CONF_HISTORY_COUNT_ENABLED,
    CONF_HISTORY_ENABLED,
    CONF_HISTORY_MODE,
    CONF_HISTORY_TIME_ENABLED,
    CONF_HISTORY_TIME_WINDOW,
    CONF_IGNORE_DUPLICATE,
    CONF_INPUT_ENTITIES,
    CONF_MAX_TOKENS,
    CONF_MODEL_NAME,
    CONF_PROMPT_AUTOMATION,
    CONF_PROMPT_DEFAULT,
    CONF_SHOW_PANEL,
    CONF_SUGGESTIONS_REFRESH_DAYS,
    CONF_TEMPERATURE,
    CONF_TTS_CUSTOM_TEMPLATE,
    CONF_TTS_ENTITIES,
    CONF_TTS_ENTITY_ID,
    CONF_TTS_INPUT_ENTITY,
    CONF_TTS_MODE,
    CONF_TTS_SPEAK_VOLUME,
    CONF_TTS_MUTE_AFTER,
    CONF_TTS_MUTE_ENTITY_ID,
    DEFAULT_PROMPT_AUTOMATION,
    DEFAULT_PROMPT_DEFAULT,
    DEFAULT_HISTORY_COUNT_ENABLED,
    DEFAULT_HISTORY_TIME_ENABLED,
    DEFAULT_DISABLE_THINKING,
    DEFAULT_SUGGESTIONS_REFRESH_DAYS,
    DEFAULT_SHOW_PANEL,
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


class _TriggerExpressionParser:
    """Safe recursive-descent parser for boolean trigger expressions.

    Grammar (case-insensitive):
        expr    := or_expr
        or_expr := and_expr ("or" and_expr)*
        and_expr := unary ("and" unary)*
        unary   := "(" expr ")" | index
        index   := integer >= 0

    No eval() — builds a callable that resolves trigger indexes against
    the automation's trigger list.
    """

    def __init__(self, text: str) -> None:
        # Normalize tokens
        self.tokens = (
            text.replace("(", " ( ")
            .replace(")", " ) ")
            .split()
        )
        self.pos = 0

    def peek(self) -> str:
        return self.tokens[self.pos].lower() if self.pos < len(self.tokens) else ""

    def next(self) -> str:
        tok = self.peek()
        self.pos += 1
        return tok

    def parse(self):
        """Return a callable: lambda automation, coordinator -> bool."""
        node = self._parse_or()
        if self.pos < len(self.tokens):
            raise ValueError(f"Unexpected token '{self.peek()}'")
        return node

    def _parse_or(self):
        node = self._parse_and()
        while self.peek() == "or":
            self.next()
            rhs = self._parse_and()
            node = _OrNode(node, rhs)
        return node

    def _parse_and(self):
        node = self._parse_unary()
        while self.peek() == "and":
            self.next()
            rhs = self._parse_unary()
            node = _AndNode(node, rhs)
        return node

    def _parse_unary(self):
        tok = self.next()
        if tok == "(":
            node = self._parse_or()
            if self.next() != ")":
                raise ValueError("Missing closing parenthesis")
            return node
        if tok.isdigit():
            idx = int(tok)
            return _IndexNode(idx)
        raise ValueError(f"Unexpected token '{tok}'")


class _IndexNode:
    def __init__(self, index: int) -> None:
        self.index = index

    def __call__(self, automation, coordinator) -> bool:
        return coordinator._trigger_satisfied(automation, self.index)


class _AndNode:
    def __init__(self, left, right) -> None:
        self.left = left
        self.right = right

    def __call__(self, automation, coordinator) -> bool:
        return self.left(automation, coordinator) and self.right(automation, coordinator)


class _OrNode:
    def __init__(self, left, right) -> None:
        self.left = left
        self.right = right

    def __call__(self, automation, coordinator) -> bool:
        return self.left(automation, coordinator) or self.right(automation, coordinator)


class DynamicAutomation:
    """Represents a dynamically created automation rule.

    Supports multiple triggers (entity+condition pairs) combined with an
    AND/OR logic, optional one-shot behavior (auto-remove after firing),
    and persisted execution records for debugging.
    """

    def __init__(
        self,
        automation_id: str,
        triggers: list[dict[str, str]],
        trigger_logic: str = "or",
        prompt: str = "",
        description: str = "",
        one_shot: bool = False,
        expression: str = "",
        language: str = "",
    ) -> None:
        self.automation_id = automation_id
        # triggers: list of {"entity_id": str, "condition": str} or
        # {"type": "time", "time": "HH:MM"} for time-based triggers
        self.triggers: list[dict[str, str]] = triggers or []
        self.trigger_logic = trigger_logic  # "and" | "or" (legacy, used as default)
        # Boolean expression combining trigger indexes, e.g. "(0 and 1) or 2"
        self.expression = expression or ""
        self.prompt = prompt
        self.description = description
        self.one_shot = one_shot
        # Language the automation was created in (detected from user input).
        # Used at trigger time so reminders reply in the same language the
        # user spoke when creating them, regardless of the current HA config.
        self.language = language or ""
        # Execution records (recent first), kept in-memory + persisted
        self.records: list[dict] = []

    # ── Backward compatibility accessors ────────────────────────────────
    @property
    def entity_id(self) -> str:
        """First entity trigger (legacy single-entity view)."""
        for t in self.triggers:
            if t.get("type", "entity") == "entity":
                return t.get("entity_id", "")
        return ""

    @entity_id.setter
    def entity_id(self, value: str) -> None:
        if self.triggers:
            self.triggers[0]["entity_id"] = value
        else:
            self.triggers = [{"entity_id": value, "condition": ""}]

    @property
    def condition(self) -> str:
        """First entity trigger's condition (legacy view)."""
        for t in self.triggers:
            if t.get("type", "entity") == "entity":
                return t.get("condition", "")
        return ""

    @condition.setter
    def condition(self, value: str) -> None:
        if self.triggers:
            self.triggers[0]["condition"] = value
        else:
            self.triggers = [{"entity_id": "", "condition": value}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "automation_id": self.automation_id,
            "triggers": self.triggers,
            "trigger_logic": self.trigger_logic,
            "expression": self.expression,
            "prompt": self.prompt,
            "description": self.description,
            "one_shot": self.one_shot,
            "language": self.language,
            "records": self.records[-30:],  # ring buffer, recent 30
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DynamicAutomation":
        triggers = data.get("triggers")
        if not triggers:
            # Legacy single-entity format
            triggers = [{
                "entity_id": data.get("entity_id", ""),
                "condition": data.get("condition", ""),
            }]
        auto = cls(
            automation_id=data["automation_id"],
            triggers=triggers,
            trigger_logic=data.get("trigger_logic", "or"),
            prompt=data.get("prompt", ""),
            description=data.get("description", ""),
            one_shot=bool(data.get("one_shot", False)),
            expression=data.get("expression", ""),
            language=data.get("language", ""),
        )
        auto.records = data.get("records", []) or []
        return auto

    def add_record(self, record: dict) -> None:
        """Append an execution record, keeping the ring buffer bounded."""
        self.records.append(record)
        if len(self.records) > 30:
            self.records = self.records[-30:]


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
    last_input: str = ""
    last_input_entity: str = ""
    last_input_time: str = ""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry_data: dict[str, Any],
        config_entry_options: dict[str, Any],
        entry_id: str = "",
    ) -> None:
        self.hass = hass
        self._data = dict(config_entry_data)
        self._options = dict(config_entry_options)
        self._entry_id = entry_id

        # Conversation history
        self._history: list[LLMChatMessage] = []

        # Language detected from the most recent user input (used so that
        # automations created in this request reply in the same language when
        # triggered later). Falls back to HA config language when empty.
        self._current_input_lang: str = ""

        # Registered state listeners (input sensors)
        self._state_listeners: list[callable] = []

        # Dynamic automations
        self._automations: dict[str, DynamicAutomation] = {}
        self._automation_listeners: dict[str, callable] = {}
        self._disabled_automations_set: set = set()

        # Storage for persistence — per-instance key so multiple config
        # entries never clobber each other's automations/history/state.
        # Data from the legacy shared key is migrated on first load.
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}_{entry_id}" if entry_id else STORAGE_KEY,
        )
        self._legacy_store = (
            Store(hass, STORAGE_VERSION, STORAGE_KEY) if entry_id else None
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
    def disable_thinking(self) -> bool:
        """Disable DeepSeek thinking mode for faster responses on simple tasks.
        Has no effect on non-DeepSeek APIs (the param is simply ignored)."""
        val = self._data.get(CONF_DISABLE_THINKING)
        if val is None:
            val = self._options.get(CONF_DISABLE_THINKING, DEFAULT_DISABLE_THINKING)
        return bool(val)

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
    def tts_entities(self) -> list[str]:
        """All configured output devices (Task 4b: multi-device routing).
        Falls back to the legacy single tts_entity_id for backward compat."""
        multi = self._options.get(CONF_TTS_ENTITIES, [])
        if multi:
            return [e for e in multi if e]
        legacy = (
            self._options.get(CONF_TTS_ENTITY_ID, "")
            or self._data.get(CONF_TTS_ENTITY_ID, "")
        )
        return [legacy] if legacy else []

    @property
    def tts_entity_id(self) -> str:
        """Default output device (first configured, else legacy single)."""
        devices = self.tts_entities
        if devices:
            return devices[0]
        return self._options.get(CONF_TTS_ENTITY_ID, "") or self._data.get(CONF_TTS_ENTITY_ID, "")

    @property
    def tts_input_entity(self) -> str:
        """Input device currently speaking (for TTS routing)."""
        return self._options.get(CONF_TTS_INPUT_ENTITY, "")

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
    def access_token(self) -> str:
        """Long-lived access token for AI Chat panel API calls."""
        return self._options.get(CONF_ACCESS_TOKEN) or self._data.get(CONF_ACCESS_TOKEN, "")

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
    def history_count_enabled(self) -> bool:
        # Legacy migration: if old history_mode selector is present and the new
        # switches were never set, honor the legacy mode selection.
        if CONF_HISTORY_MODE in self._options and CONF_HISTORY_COUNT_ENABLED not in self._options:
            return self._options.get(CONF_HISTORY_MODE) == HISTORY_MODE_COUNT
        return self._options.get(CONF_HISTORY_COUNT_ENABLED, DEFAULT_HISTORY_COUNT_ENABLED)

    @property
    def history_time_enabled(self) -> bool:
        if CONF_HISTORY_MODE in self._options and CONF_HISTORY_TIME_ENABLED not in self._options:
            return self._options.get(CONF_HISTORY_MODE) == HISTORY_MODE_TIME
        return self._options.get(CONF_HISTORY_TIME_ENABLED, DEFAULT_HISTORY_TIME_ENABLED)

    @property
    def history_count(self) -> int:
        return int(self._options.get(CONF_HISTORY_COUNT, 10))

    @property
    def history_time_window(self) -> int:
        return int(self._options.get(CONF_HISTORY_TIME_WINDOW, 60))

    @property
    def show_panel(self) -> bool:
        """Whether the AI Chat sidebar panel should be shown for this instance."""
        return self._options.get(CONF_SHOW_PANEL, DEFAULT_SHOW_PANEL)

    @property
    def suggestions_refresh_days(self) -> int:
        """TTL in days for the chat suggestions cache."""
        val = self._data.get(CONF_SUGGESTIONS_REFRESH_DAYS)
        if val is None:
            val = self._options.get(CONF_SUGGESTIONS_REFRESH_DAYS, DEFAULT_SUGGESTIONS_REFRESH_DAYS)
        return int(val)

    @property
    def title(self) -> str:
        """Human-readable title of this config entry (instance name)."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        return entry.title if entry else ""

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
        old_state: State | None = event.data.get("old_state")

        if new_state is None:
            return

        state_text = str(new_state.state).strip()

        # Skip state restoration at startup/reload: when an entity is
        # (re)registered with its previous value, old_state is None.
        # Record the text so a subsequent identical phantom update is
        # still caught by duplicate detection, but do NOT process it —
        # otherwise the last voice command would re-execute on every
        # HA restart.
        if old_state is None:
            _LOGGER.debug(
                "Ignoring restored state for %s (entity just loaded): '%s'",
                entity_id, state_text,
            )
            if state_text and state_text not in ("unavailable", "unknown", "none"):
                self._last_states[entity_id] = state_text
            return

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
        self._schedule_storage_save()

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
        output_devices = self._build_output_devices_info()

        context = {
            "time": now.strftime("%H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "exposed_entities": exposed_entities,
            "output_devices": output_devices,
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

        Format: entity_id, friendly_name, state, area, aliases
        This is compact, easy for LLMs to parse, and includes only
        whitelisted entities in non-error states.
        """
        lines = ["entity_id,name,state,area,aliases"]
        domains = self.domains_whitelist
        entity_ids = self.entities_whitelist
        registry = self.hass.data.get("entity_registry")

        _csv_t0 = asyncio.get_running_loop().time()
        _area_lookups = 0

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
            _area_lookups += 1
            aliases_str = ""
            if registry is not None:
                entry = registry.async_get(entity_id)
                if entry and entry.aliases:
                    str_aliases = [a for a in entry.aliases if isinstance(a, str)]
                    if str_aliases:
                        aliases_str = ";".join(str_aliases).replace(",", " ")

            lines.append(f"{entity_id},{friendly},{state_val},{area},{aliases_str}")

        result = "\n".join(lines)
        _csv_dt = asyncio.get_running_loop().time() - _csv_t0
        _LOGGER.info(
            "Entity CSV built: %.3fs (%d entities, %d area lookups, %d chars)",
            _csv_dt, len(lines) - 1, _area_lookups, len(result),
        )
        return result

    def _get_area_name(self, entity_id: str) -> str:
        """Get the area name for an entity, if available.

        Uses the entity registry to resolve area_id, then the area registry
        to get the human-readable area name."""
        try:
            registry = self.hass.data.get("entity_registry")
            if registry is None:
                return ""
            entry = registry.async_get(entity_id)
            if entry is None or not entry.area_id:
                return ""
            area_registry = self.hass.data.get("area_registry")
            if area_registry is None:
                return ""
            area = area_registry.async_get_area(entry.area_id)
            if area is None:
                return ""
            return area.name or ""
        except Exception as exc:  # never break entity CSV building
            _LOGGER.debug("area lookup failed for %s: %s", entity_id, exc)
            return ""

    @staticmethod
    def _detect_language(text: str) -> str:
        """Detect the language of a user input string.

        Lightweight heuristic based on Unicode script ranges — no external
        dependency. Returns a 2-letter code ("zh", "ja", "ko", "ru", "en", …).
        CJK characters → "zh" (Japanese hiragana/katakana → "ja"); Cyrillic →
        "ru"; otherwise defaults to the config language or "en".
        """
        if not text:
            return ""
        # Count CJK ideographs, Hiragana, Katakana, Hangul, Cyrillic
        cjk = hira = kata = hangul = cyrillic = 0
        for ch in text:
            cp = ord(ch)
            if 0x4E00 <= cp <= 0x9FFF:
                cjk += 1
            elif 0x3040 <= cp <= 0x309F:
                hira += 1
            elif 0x30A0 <= cp <= 0x30FF:
                kata += 1
            elif 0xAC00 <= cp <= 0xD7AF:
                hangul += 1
            elif 0x0400 <= cp <= 0x04FF:
                cyrillic += 1
        if hira or kata:
            return "ja"
        if hangul:
            return "ko"
        if cjk:
            return "zh"
        if cyrillic:
            return "ru"
        # Latin/other scripts: assume English (most common default)
        return "en"

    def _build_output_devices_info(self) -> str:
        """Build a compact list of configured output (TTS) devices with location.

        Format: entity_id, friendly_name, area
        Used to let the model pick the best device based on input location."""
        devices = self.tts_entities
        if not devices:
            return "(none configured)"
        lines = ["entity_id,name,area"]
        for entity_id in devices:
            state_obj = self.hass.states.get(entity_id)
            friendly = ""
            if state_obj:
                friendly = state_obj.attributes.get("friendly_name", "")
            area = self._get_area_name(entity_id)
            lines.append(f"{entity_id},{friendly or entity_id},{area}")
        return "\n".join(lines)

    def _build_input_source_info(self, entity_id: str) -> str:
        """Describe where the current user input comes from (device + area)."""
        if not entity_id or entity_id in ("service_call", "chat_ui"):
            return "AI Chat panel / API call"
        area = self._get_area_name(entity_id)
        state_obj = self.hass.states.get(entity_id)
        friendly = ""
        if state_obj:
            friendly = state_obj.attributes.get("friendly_name", "")
        label = friendly or entity_id
        return f"{label} ({entity_id}) in area '{area}'" if area else f"{label} ({entity_id})"

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
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("LLM raw query failed with status %d", resp.status)
                        return None
                    data = await resp.json()
            choices = data.get("choices", [])
            if not choices:
                _LOGGER.warning("LLM raw query returned no choices")
                return None
            content = choices[0].get("message", {}).get("content", "")
            result = content.strip() or None
            _LOGGER.debug("LLM raw query returned %d chars", len(content))
            return result
        except Exception as exc:
            _LOGGER.warning("LLM raw query failed: %s", exc)
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

        # DeepSeek thinking mode: disable for faster responses on simple HA
        # control tasks (saves ~1-2s by skipping the reasoning chain).
        # Non-DeepSeek APIs ignore this param. Configurable per instance.
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}

        max_retries = 2
        last_error = None
        # Perf: measure LLM API round-trip (the usual bottleneck)
        _api_t0 = asyncio.get_running_loop().time()
        _prompt_chars = sum(len(m.get("content", "")) for m in messages)

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
                        timeout=aiohttp.ClientTimeout(total=90),
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

                _LOGGER.info("LLM raw response received (%d chars): %s", len(content), content[:200])

                _api_dt = asyncio.get_running_loop().time() - _api_t0
                _LOGGER.info(
                    "LLM API timing: %.2fs (prompt %d chars / ~%d tokens, response %d chars, attempt %d)",
                    _api_dt, _prompt_chars, _prompt_chars // 4, len(content), attempt + 1,
                )

                # Try to parse as JSON (handle extra text after JSON)
                parsed = self._parse_llm_json(content)

                if parsed is None:
                    _LOGGER.error(
                        "Failed to parse LLM response as JSON (attempt %d/%d)\nRaw: %s",
                        attempt + 1, max_retries + 1, content[:1500],
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

    @staticmethod
    def _parse_llm_json(content: str) -> dict[str, Any] | None:
        """Robustly parse an LLM JSON response.

        LLMs occasionally wrap JSON in markdown code fences, prepend/append
        prose, or emit trailing commas. This recovers from all of those:
        1. strip ```json ... ``` fences
        2. extract the outermost {...} object
        3. direct json.loads
        4. fix trailing commas and retry
        Returns the parsed dict, or None if nothing parseable was found.
        """
        if not content or not content.strip():
            return None
        text = content.strip()
        # 1. Markdown code fences (```json ... ``` or ``` ... ```)
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()
        # 2. Extract the outermost {...} object with brace matching (ignores
        #    braces inside strings, stops at the matching close), so trailing
        #    stray braces after the object don't break the parse
        start = text.find('{')
        if start == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    text = text[start:i + 1]
                    break
        if not text.startswith('{'):
            return None
        # 3. Direct parse
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if parsed is None:
            # 4. Trailing commas are the most common LLM JSON mistake: fix
            #    ",]" / ",}" before retrying
            fixed = re.sub(r",\s*([}\]])", r"\1", text)
            if fixed != text:
                try:
                    parsed = json.loads(fixed)
                except json.JSONDecodeError:
                    parsed = None
        if isinstance(parsed, dict):
            return parsed
        return None

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
        """Truncate history: apply enabled constraints independently.

        - count_enabled + time_enabled (default): both constraints apply
        - only one enabled: only that constraint applies
        - both disabled: no truncation (keep full history)
        """
        if not self.history_enabled:
            self._history = self._history[-1:]  # keep only current turn
            return
        if self.history_count_enabled:
            max_count = max(self.history_count, 1)
            if len(self._history) > max_count:
                self._history = self._history[-max_count:]
        if self.history_time_enabled:
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

        # Perf/debug: log how much history is being sent
        hist_count = len(self._history)
        hist_chars = sum(len(m.content) for m in self._history)
        _LOGGER.info(
            "Messages built: %d total (%d system + %d history + 1 user), history %d msgs / %d chars",
            len(messages), 1, hist_count, hist_count, hist_chars,
        )
        return messages

    # ------------------------------------------------------------------
    # Main processing pipeline
    # ------------------------------------------------------------------

    async def _async_process_user_input(
        self, entity_id: str, user_text: str, source: str = ""
    ) -> None:
        """Process a user input through multi-step reasoning loop.

        Args:
            entity_id: The source entity_id ("service_call" for API calls, or sensor entity_id).
            user_text: The text to process.
            source: Input source marker ("voice" for chat UI voice input, "" otherwise).
                    Used later for TTS routing decisions (Task 4a).

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

        _total_t0 = asyncio.get_running_loop().time()

        # Record the last user input (for sensor attributes / history display)
        self.last_input = user_text
        self.last_input_entity = entity_id
        self.last_input_time = dt_util.now().isoformat()
        # Detect the input language so automations created during this request
        # reply in the same language when triggered later (regardless of HA config).
        self._current_input_lang = self._detect_language(user_text)
        # Mark processing as started and clear the previous response BEFORE
        # notifying, otherwise the panel would see the stale last_response with
        # in_progress=False and display the PREVIOUS reply as the new answer.
        self.in_progress = True
        self.current_round = 0
        self.last_response = None
        self._async_notify_listeners()

        start_time = asyncio.get_running_loop().time()
        max_iterations = MAX_REASONING_ITERATIONS
        timeout = REASONING_TIMEOUT

        # Add user message to history
        self._add_to_history(LLMChatMessage(role="user", content=user_text))

        # Expose entities list for system context
        _ctx_t0 = asyncio.get_running_loop().time()
        exposed = self._build_exposed_entities_list()
        # Task 4b: describe the input source (device + area) so the model can
        # route the TTS reply to the most appropriate output device.
        input_source = self._build_input_source_info(entity_id)
        _ctx_dt = asyncio.get_running_loop().time() - _ctx_t0
        _LOGGER.info("Context build (exposed entities + input source): %.3fs", _ctx_dt)

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
            input_source=input_source,
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
            _round_t0 = asyncio.get_running_loop().time()
            response = await self._async_query_llm(current_messages)
            _llm_dt = asyncio.get_running_loop().time() - _round_t0

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
                "Round %d: tts_text='%s', steps=%s (LLM %.2fs, %d steps)",
                iteration, str(tts_text)[:100], str(steps)[:200], _llm_dt, len(steps)
            )

            # Accumulate TTS only when task is fully complete (no more steps)
            # If LLM speaks but still has actions, delay the speech to final round
            # — UNLESS all steps are actions (no get_states): the LLM already knows
            # the outcome, so its tts_text is the final reply.
            if tts_text and not steps:
                cumulative_tts.append(tts_text)

            # Track each round for debug
            all_rounds.append({
                "round": iteration,
                "tts_text": tts_text,
                "steps": steps,
                "output_device": response.get("output_device", ""),
            })

            # If no steps, we're done
            if not steps:
                _LOGGER.info(
                    "No steps returned, reasoning complete after %d rounds",
                    iteration
                )
                break

            all_steps_ever.extend(steps)

            # Optimization: if all steps are actions that don't need observation
            # (call_service / create_automation / tts_speak) and the LLM already
            # provided tts_text, execute and finish WITHOUT another LLM round.
            # Only get_states needs a follow-up round (the LLM must observe results).
            needs_observation = any(
                s.get("action") in (ACTION_GET_STATES, ACTION_INSPECT)
                for s in steps
            )

            # Execute steps and collect results for feedback
            step_feedback = []
            if self.executor:
                _exec_t0 = asyncio.get_running_loop().time()
                step_results = await self.executor.async_execute_steps(steps)
                _exec_dt = asyncio.get_running_loop().time() - _exec_t0
                _LOGGER.info(
                    "Steps executed: %.3fs (%d steps)",
                    _exec_dt, len(steps),
                )
                for result in step_results:
                    action = result.get("action", "unknown")
                    success = result.get("success", False)
                    step_result_data = result.get("result", {})

                    if action in (ACTION_GET_STATES, ACTION_INSPECT):
                        # get_states: feed back observed states + service names (compact).
                        # Skip per-service descriptions/fields — the system prompt
                        # already documents common services, and full field details
                        # bloat the context (1777+ chars per get_states round).
                        obs = step_result_data.get("observed", [])
                        for o in obs:
                            ent_id = o.get("entity_id", "?")
                            ent_state = o.get("state", "unknown")
                            friendly = o.get("attributes", {}).get("friendly_name", "")
                            unit = o.get("attributes", {}).get("unit_of_measurement", "")
                            label = f"{friendly} ({ent_id})" if friendly else ent_id
                            val = f"{ent_state} {unit}" if unit else str(ent_state)
                            services = o.get("services", [])
                            line = f"  - {label}: {val}"
                            if services:
                                svc_names = [s.get("name", "?") for s in services if isinstance(s, dict)]
                                line += f" [services: {', '.join(svc_names)}]"
                            step_feedback.append(line)

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
                        triggers = step_result_data.get("triggers")
                        logic = step_result_data.get("trigger_logic", "or")
                        one_shot = step_result_data.get("one_shot", False)
                        if success and auto_id:
                            if triggers:
                                trig_desc = ", ".join(
                                    f"{t.get('entity_id','?')} {t.get('condition','')}"
                                    for t in triggers
                                )
                                extra = f" [one-shot]" if one_shot else ""
                                step_feedback.append(
                                    f"  - create_automation: DONE (id={auto_id[:8]}, "
                                    f"triggers[{logic}]: {trig_desc}{extra})"
                                )
                            else:
                                step_feedback.append(
                                    f"  - create_automation: DONE (id={auto_id[:8]}, "
                                    f"entity={step_result_data.get('entity_id','')}, "
                                    f"condition={step_result_data.get('condition','')})"
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
                # Optimization: if no step needs observation (no get_states),
                # the LLM doesn't need to see the results — finish now.
                # This saves one full LLM API round-trip (4-6s) for simple
                # action requests like "turn on the light".
                if not needs_observation:
                    _LOGGER.info(
                        "Action-only steps executed (no observation needed), "
                        "finishing after %d rounds (saved 1 LLM round)",
                        iteration,
                    )
                    # Capture the LLM's tts_text from this round as the final reply
                    if tts_text:
                        cumulative_tts.append(tts_text)
                    break
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

        # Speak TTS (skip for AI Chat — voice uses browser TTS, text uses none)
        should_tts = True
        if entity_id in ("service_call", "chat_ui"):
            should_tts = False
        # Task 4b: route to the output device the LLM chose (if any).
        output_device = self._output_device_from_rounds(all_rounds)
        if final_tts and should_tts:
            await self._async_speak_tts(final_tts, output_device=output_device)

        # Add only the FINAL assistant response to history (not intermediate rounds)
        self._add_to_history(
            LLMChatMessage(
                role="assistant",
                content=final_tts,
            )
        )
        _LOGGER.info("Added to history: assistant='%s' (total %d msgs)", final_tts[:80], len(self._history))

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
        _total_dt = asyncio.get_running_loop().time() - _total_t0
        _LOGGER.info(
            "TOTAL processing time: %.2fs (context %.2fs + %d rounds, input '%s')",
            _total_dt, _ctx_dt, iteration, user_text[:60],
        )

    def _output_device_from_rounds(self, rounds: list[dict]) -> str:
        """Extract the output_device chosen by the LLM from reasoning rounds.

        Returns the last non-empty output_device the model requested, or ""
        if none was specified (fall back to the default device)."""
        chosen = ""
        for rnd in rounds:
            dev = rnd.get("output_device") or ""
            if dev and dev in self.tts_entities:
                chosen = dev
        return chosen

    def _build_exposed_entities_list(self) -> str:
        """Build a summary of available entities for the system prompt.

        Compact one-line-per-entity format. Skips internal/noise entities that
        the LLM should never control (sun, backup, llm_* sensors, etc.).
        """
        # Domains/entities that are noise for the LLM (never actionable)
        _SKIP_PREFIXES = (
            "sensor.sun_", "sensor.backup_", "sensor.llm_",
            "sensor.zone_", "sensor.time_",
        )
        lines = []
        # Read entity registry for aliases
        registry = self.hass.data.get("entity_registry")
        for state_obj in self.hass.states.async_all():
            domain = state_obj.domain
            allowed = self.domains_whitelist
            if allowed and domain not in allowed:
                continue
            eid = state_obj.entity_id
            if eid.startswith(_SKIP_PREFIXES):
                continue
            friendly = state_obj.attributes.get("friendly_name", eid)
            # Append aliases if any (only user-configured strings, not HA internal enums)
            aliases_str = ""
            if registry is not None:
                entry = registry.async_get(eid)
                if entry and entry.aliases:
                    str_aliases = [a for a in entry.aliases if isinstance(a, str)]
                    if str_aliases:
                        aliases_str = " [" + ", ".join(str_aliases) + "]"
            lines.append(f"  - {eid} ({friendly}{aliases_str}): {state_obj.state}")
        return "\n".join(lines)

    async def _async_process_automation_trigger(
        self, automation: DynamicAutomation, state: State
    ) -> None:
        """Process a dynamic automation trigger via LLM.
        
        Passes the full available entities list to the LLM so it can
        determine the correct action and entity IDs dynamically.
        Records the execution for the debug UI; one-shot automations
        remove themselves after firing.
        """
        record = {
            "time": dt_util.utcnow().isoformat(),
            "trigger_entity": state.entity_id,
            "trigger_state": str(state.state),
            "result": "",
            "ok": True,
        }
        _LOGGER.info(
            "Automation '%s' triggered by %s = %s",
            automation.automation_id,
            state.entity_id,
            state.state,
        )

        # Build entity context (CSV format, compact and LLM-friendly)
        # Build rich device list with area info from registry
        entity_context = "Available Devices (entity_id,domain,name,state,unit,extra):\n" + self._build_entity_csv()
        
        action_prompt = automation.prompt or automation.description or "Execute the configured automation action"
        
        # Determine language: prefer the language stored when the automation
        # was created (detected from the user's input text), fall back to the
        # current HA config language. This ensures a reminder created in
        # Chinese replies in Chinese even if HA is set to English (and vice
        # versa).
        lang_code = automation.language or (self.hass.config.language or "en").split("-")[0]
        lang_names = {"zh": "Chinese", "en": "English", "ja": "Japanese", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese", "ko": "Korean", "ru": "Russian"}
        lang_name = lang_names.get(lang_code, "English")

        messages = self._build_messages_for_llm(
            user_input=(
                f"AUTOMATION TRIGGERED\n"
                f"Trigger: {state.entity_id} = {state.state}\n"
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
            record["ok"] = False
            record["result"] = "LLM call failed"
            automation.add_record(record)
            await self._async_save_storage()
            return

        tts_text = response.get("tts_text", "")
        steps = response.get("steps", [])

        # If LLM returned empty steps, try fallback matching
        if not steps:
            _LOGGER.info("Automation returned empty steps, trying fallback entity match")
            steps = self._try_fallback_automation_action(automation)
            if steps:
                _LOGGER.info("Fallback matched: %s", steps)

        # Reminder fallback: the LLM produced neither an action nor speech.
        # For reminder-type automations ("提醒我出门"), speak the prompt itself
        # so a silent no-op never swallows the reminder.
        if not steps and not tts_text and (automation.prompt or automation.description):
            reminder = self._clean_reminder_text(
                automation.prompt or automation.description
            )
            if reminder:
                _LOGGER.info(
                    "Automation '%s': no action from LLM, speaking reminder: %s",
                    automation.automation_id[:8], reminder,
                )
                tts_text = reminder

        # Execute steps
        exec_ok = True
        if steps and self.executor:
            try:
                results = await self.executor.async_execute_steps(steps)
                failed = [r for r in results if not r.get("success", True)]
                if failed:
                    exec_ok = False
                    record["result"] = "; ".join(
                        f"{r.get('error', '?')}" for r in failed[:2]
                    )
            except Exception as exc:
                exec_ok = False
                record["result"] = str(exc)

        # Speak TTS if text is present
        if tts_text:
            _LOGGER.info(
                "Automation '%s': speaking TTS: %s (output_device=%s)",
                automation.automation_id[:8], tts_text[:80],
                response.get("output_device", "") or "(default)",
            )
            await self._async_speak_tts(
                tts_text, output_device=response.get("output_device", "")
            )
        else:
            _LOGGER.info(
                "Automation '%s': no TTS text to speak", automation.automation_id[:8]
            )

        # Record execution for debug UI
        record["result"] = record["result"] or tts_text or (
            f"executed {len(steps)} step(s)" if steps else "no action"
        )
        record["ok"] = exec_ok
        record["steps"] = len(steps)
        automation.add_record(record)
        await self._async_save_storage()

        # One-shot automations remove themselves after firing
        if automation.one_shot:
            _LOGGER.info(
                "One-shot automation '%s' fired — removing",
                automation.automation_id[:8],
            )
            await self.async_remove_automation(automation.automation_id)

    # ------------------------------------------------------------------
    # Dynamic Automation Management
    # ------------------------------------------------------------------

    async def async_create_automation(
        self,
        entity_id: str = "",
        condition: str = "",
        prompt: str = "",
        description: str = "",
        triggers: list[dict[str, str]] | None = None,
        trigger_logic: str = "or",
        one_shot: bool = False,
        expression: str = "",
    ) -> str | None:
        """Create a dynamic automation.

        Accepts either the legacy (entity_id, condition) pair or a list of
        triggers ({"entity_id", "condition"} or {"type": "time", "time": ...})
        combined with AND/OR logic. Pass an `expression` (e.g. "(0 and 1) or 2")
        for complex boolean combinations with parentheses. one_shot automations
        remove themselves after their first execution.

        Returns the automation_id on success, or None on failure.
        """
        if not triggers:
            triggers = [{"entity_id": entity_id, "condition": condition}]
        triggers = [
            t for t in triggers
            if t.get("entity_id") or t.get("time") or t.get("datetime")
        ]
        if not triggers:
            _LOGGER.error("create_automation: no valid triggers provided")
            return None

        # Some LLMs put one_shot inside a trigger dict instead of at the top
        # level. Hoist it to the automation and drop it from the trigger (it
        # is automation-level semantics, not per-trigger).
        for trig in triggers:
            if trig.get("one_shot") is True:
                one_shot = True
                trig.pop("one_shot", None)
                _LOGGER.debug(
                    "create_automation: hoisted one_shot from trigger to automation"
                )

        # Duplicate detection: the ReAct loop can make the LLM re-emit the same
        # create_automation step across rounds. Reuse the existing automation
        # instead of stacking identical copies.
        trig_key = json.dumps(triggers, sort_keys=True, ensure_ascii=False)
        for existing in list(self._automations.values()):
            if (
                existing.prompt == prompt
                and existing.description == description
                and json.dumps(existing.triggers, sort_keys=True, ensure_ascii=False)
                == trig_key
            ):
                _LOGGER.info(
                    "create_automation: duplicate of '%s', reusing it",
                    existing.automation_id[:8],
                )
                return existing.automation_id

        automation_id = str(uuid.uuid4())

        automation = DynamicAutomation(
            automation_id=automation_id,
            triggers=triggers,
            trigger_logic=trigger_logic if trigger_logic in ("and", "or") else "or",
            prompt=prompt,
            description=description,
            one_shot=one_shot,
            expression=expression or "",
            language=self._current_input_lang,
        )

        # Register the listeners (one per entity trigger + time triggers)
        try:
            self._register_automation_listener(automation)
            self._automations[automation_id] = automation

            # Persist to storage
            await self._async_save_storage()

            _LOGGER.info(
                "Created dynamic automation '%s': %d triggers (expr=%s)%s",
                automation_id,
                len(triggers),
                expression or trigger_logic,
                " [one-shot]" if one_shot else "",
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

    def _compute_next_fire(self, trigger: dict, now: datetime) -> datetime | None:
        """Compute the next fire time for a time trigger.

        Supports schedules:
          - once:    one-shot at `datetime` ("YYYY-MM-DDTHH:MM[:SS]"), no repeat
          - daily:   every day at `time` (HH:MM)  [default, backward compatible]
          - weekly:  at `time` on `weekdays` (1=Mon..7=Sun)
          - monthly: at `time` on `days_of_month` (1..31, invalid days skipped)
        Returns None when there is no future occurrence (e.g. past one-shot).
        """
        schedule = str(trigger.get("schedule", "") or "")
        if not schedule and trigger.get("datetime"):
            schedule = "once"
        if not schedule:
            schedule = "daily"
        time_str = str(trigger.get("time", "")).strip()
        try:
            parts = [int(x) for x in time_str.split(":")] if time_str else []
            hour = parts[0] if len(parts) > 0 else 0
            minute = parts[1] if len(parts) > 1 else 0
        except (ValueError, AttributeError):
            hour, minute = 0, 0
        # Optional second-level precision (e.g. time "23:59:45" or second field)
        try:
            second = int(trigger.get("second", 0) or 0)
            if len(parts) > 2:
                second = parts[2]
        except (ValueError, AttributeError, TypeError):
            second = 0
        if not (0 <= second <= 59):
            second = 0

        def _at(d: datetime) -> datetime:
            return d.replace(hour=hour, minute=minute, second=second, microsecond=0)

        if schedule == "once":
            dt_str = str(trigger.get("datetime", "")).strip()
            if not dt_str:
                # Some LLMs emit once with only `time` (no datetime). Treat it
                # as the next HH:MM — fires once, never re-registers.
                if time_str:
                    fire = _at(now)
                    if fire <= now:
                        fire = fire + timedelta(days=1)
                    _LOGGER.debug(
                        "Automation time trigger: once+time fallback → %s", fire
                    )
                    return fire
                _LOGGER.warning(
                    "Automation time trigger: once schedule without datetime, skipped"
                )
                return None
            try:
                fire = datetime.fromisoformat(dt_str)
            except ValueError:
                _LOGGER.warning("Automation time trigger: invalid datetime %r", dt_str)
                return None
            if fire.tzinfo is None:
                fire = fire.replace(tzinfo=now.tzinfo)
            return fire if fire > now else None

        if schedule == "weekly":
            weekdays = {int(w) for w in trigger.get("weekdays", []) or [] if str(w).isdigit()}
            weekdays = {w for w in weekdays if 1 <= w <= 7}
            if not weekdays:
                weekdays = set(range(1, 8))  # every day fallback
            for offset in range(0, 8):
                candidate = _at(now + timedelta(days=offset))
                if candidate <= now:
                    continue
                # now.weekday(): 0=Mon..6=Sun; weekdays stored 1=Mon..7=Sun
                if (candidate.weekday() + 1) in weekdays:
                    return candidate
            return None

        if schedule == "monthly":
            days = {int(d) for d in trigger.get("days_of_month", []) or [] if str(d).isdigit()}
            days = {d for d in days if 1 <= d <= 31}
            if not days:
                days = {1}
            # Scan up to 62 days ahead to cover month boundaries + invalid days
            for offset in range(0, 62):
                candidate = _at(now + timedelta(days=offset))
                if candidate <= now:
                    continue
                if candidate.day in days:
                    return candidate
            return None

        # daily (default)
        fire_at = _at(now)
        if fire_at <= now:
            fire_at = fire_at + timedelta(days=1)
        return fire_at

    def _register_time_trigger(
        self, automation: "DynamicAutomation", trigger_index: int
    ) -> callable | None:
        """Register a schedule-aware time trigger.

        Computes the next occurrence (daily/weekly/monthly/once) and
        re-registers for the following one after firing, unless the
        automation is one-shot/disabled or there is no next occurrence.
        """
        from homeassistant.helpers.event import async_track_point_in_time

        trigger = automation.triggers[trigger_index]
        now = dt_util.as_local(dt_util.utcnow())
        fire_at = self._compute_next_fire(trigger, now)
        if fire_at is None:
            _LOGGER.info(
                "Automation '%s': no future occurrence for time trigger, not registering",
                automation.automation_id[:8],
            )
            return None

        def _fire(ts: datetime) -> None:
            self._async_handle_time_trigger(automation, trigger_index, ts)
            # Long-running automations repeat per their schedule; a "once"
            # schedule never re-registers (fires exactly one time).
            if (
                automation.automation_id in self._automations
                and not automation.one_shot
                and automation.automation_id not in self.disabled_automations
                and trigger.get("schedule") != "once"
            ):
                next_fire = self._compute_next_fire(
                    trigger, dt_util.as_local(dt_util.utcnow())
                )
                if next_fire is not None:
                    self._register_time_trigger(automation, trigger_index)
                else:
                    _LOGGER.info(
                        "Automation '%s': no next occurrence, schedule complete",
                        automation.automation_id[:8],
                    )

        return async_track_point_in_time(self.hass, _fire, fire_at)

    def _register_automation_listener(self, automation: "DynamicAutomation") -> None:
        """Register all listeners (one per entity trigger + time triggers)."""
        from homeassistant.helpers.event import async_track_state_change_event
        remove_fns: list[callable] = []

        for i, trigger in enumerate(automation.triggers):
            t_type = trigger.get("type", "entity")
            if t_type == "time":
                remove_fn = self._register_time_trigger(automation, i)
                if remove_fn:
                    remove_fns.append(remove_fn)
            else:
                entity_id = trigger.get("entity_id", "")
                if not entity_id:
                    continue
                remove_fns.append(
                    async_track_state_change_event(
                        self.hass,
                        entity_id,
                        lambda event, a=automation, ti=i: self._async_handle_automation_event(
                            a, ti, event
                        ),
                    )
                )

        # Store ALL remove fns so disable/unload can detach everything
        self._automation_listeners[automation.automation_id] = lambda: [
            fn() for fn in remove_fns
        ]

    def _unregister_automation_listener(self, automation_id: str) -> None:
        """Unregister all listeners for an automation."""
        remove_all = self._automation_listeners.pop(automation_id, None)
        if remove_all:
            try:
                remove_all()
            except Exception as exc:
                _LOGGER.debug("Listener cleanup for %s: %s", automation_id[:8], exc)

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
            try:
                remove_fn()
            except Exception:
                pass
        self._automation_listeners.clear()

        for automation in self._automations.values():
            self._register_automation_listener(automation)

    @callback
    def _async_handle_automation_event(
        self, automation: DynamicAutomation, trigger_index: int, event: Event
    ) -> None:
        """Handle a state change event for one trigger of an automation."""
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

        # The changed trigger must satisfy its own condition
        changed_trigger = automation.triggers[trigger_index]
        if not self._evaluate_condition(
            str(new_state.state), changed_trigger.get("condition", "")
        ):
            return

        # Evaluate the full boolean expression (AND/OR/parentheses)
        if not self._evaluate_expression(automation):
            return

        # Process the automation trigger (use add_job for thread-safety)
        self.hass.add_job(
            self._async_process_automation_trigger(automation, new_state)
        )

    @callback
    def _async_handle_time_trigger(
        self, automation: DynamicAutomation, trigger_index: int, _dt: datetime
    ) -> None:
        """Handle a time-based trigger firing."""
        if not self._is_started:
            return
        if automation.automation_id in self.disabled_automations:
            return
        if not self._evaluate_all_entity_triggers(automation):
            return
        _LOGGER.info(
            "Automation '%s' time trigger %d fired at %s",
            automation.automation_id[:8], trigger_index, _dt,
        )
        # Build a pseudo state for the time trigger
        pseudo_state = State(
            f"time.{automation.automation_id[:8]}", str(_dt.strftime("%H:%M"))
        )
        self.hass.add_job(
            self._async_process_automation_trigger(automation, pseudo_state)
        )

    def _evaluate_all_entity_triggers(self, automation: DynamicAutomation) -> bool:
        """Evaluate all entity triggers (used for time-trigger automations).

        Pure-time automations (no entity triggers) evaluate to True: when a
        time trigger fires, there is nothing else to check, so it proceeds.
        """
        has_entity = any(
            t.get("type", "entity") == "entity" for t in automation.triggers
        )
        if not has_entity:
            return True
        return self._evaluate_expression(automation)

    def _evaluate_expression(self, automation: DynamicAutomation) -> bool:
        """Evaluate the automation's boolean trigger expression.

        Expression uses trigger indexes, e.g. "0 and 1" or "(0 or 1) and 2".
        Falls back to the legacy trigger_logic (all-and / any-or) when no
        explicit expression is stored.
        """
        expr = getattr(automation, "expression", "") or ""
        if not expr:
            # Legacy: derive from trigger_logic
            if automation.trigger_logic == "and":
                return all(
                    self._trigger_satisfied(automation, i)
                    for i in range(len(automation.triggers))
                )
            return any(
                self._trigger_satisfied(automation, i)
                for i in range(len(automation.triggers))
            )
        try:
            parser = _TriggerExpressionParser(expr)
            result = parser.parse()
            return bool(result(automation, self))
        except Exception as exc:
            _LOGGER.warning(
                "Automation '%s': expression parse failed (%s), falling back to OR",
                automation.automation_id[:8], exc,
            )
            return any(
                self._trigger_satisfied(automation, i)
                for i in range(len(automation.triggers))
            )

    def _trigger_satisfied(self, automation: DynamicAutomation, index: int) -> bool:
        """Check if one trigger's current state satisfies its condition."""
        if index >= len(automation.triggers):
            return False
        trigger = automation.triggers[index]
        if trigger.get("type", "entity") != "entity":
            # Non-entity triggers (time) count as satisfied only when firing;
            # for evaluation purposes treat missing state as False
            return False
        ent_state = self.hass.states.get(trigger.get("entity_id", ""))
        if ent_state is None:
            return False
        return self._evaluate_condition(
            str(ent_state.state), trigger.get("condition", "")
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

    @staticmethod
    def _clean_reminder_text(text: str) -> str:
        """Strip reminder-style prefixes so the spoken text reads naturally.

        "提醒我出门" → "出门"; "请提醒我吃药" → "吃药"; "记得关窗" stays as-is.
        """
        t = (text or "").strip()
        for prefix in ("请提醒我", "提醒我", "请记得", "记得提醒我", "提醒"):
            if t.startswith(prefix):
                t = t[len(prefix):].strip()
                break
        # If nothing meaningful remains after stripping, keep original
        if not t:
            return (text or "").strip()
        return t

    async def _async_speak_tts(self, text: str, output_device: str = "") -> None:
        """Speak text via the configured TTS mechanism.

        Args:
            text: The text to speak.
            output_device: Optional entity_id of the target speaker
                (Task 4b multi-device routing). Defaults to the first
                configured device when empty.

        Tries to prevent speaker self-triggering (抢答) via:
        1. User-configured mute entity (media_player for volume control)
        2. Auto-detected DND switch
        3. Auto-detected sleep mode switch (fallback)
        """
        # Resolve the target device: explicit routing wins, else default
        if output_device and output_device in self.tts_entities:
            tts_entity = output_device
        else:
            tts_entity = self.tts_entity_id

        if not text:
            _LOGGER.warning("_async_speak_tts: no text to speak, skipping")
            return
        if not tts_entity:
            _LOGGER.warning(
                "_async_speak_tts: no TTS device configured (tts_entity_id is empty), "
                "cannot speak: %s", text[:80]
            )
            return
        media_domain = tts_entity.split(".")[0]

        # Collect mute mechanisms (only if user enabled anti-echo)
        _pre_tts_actions: list[tuple[str, str, dict]] = []
        _post_tts_actions: list[tuple[str, str, dict]] = []

        if media_domain == "media_player" and self.tts_mute_after:
            # Auto-detect DND/sleep switches
            for suffix in ["no_disturb", "sleep_mode"]:
                sw_id = tts_entity.replace("play_control", suffix).replace("media_player", "switch")
                if self.hass.states.get(sw_id):
                    _pre_tts_actions.append(("switch", "turn_off", {"entity_id": sw_id}))
                    _post_tts_actions.append(("switch", "turn_on", {"entity_id": sw_id}))
                    break
            # User-configured mute entity
            mute_entity = self.tts_mute_entity_id
            if mute_entity and self.hass.states.get(mute_entity):
                _pre_tts_actions.insert(0, ("media_player", "volume_mute",
                    {"entity_id": mute_entity, "is_volume_muted": False}))
                _pre_tts_actions.insert(0, ("media_player", "volume_set",
                    {"entity_id": mute_entity, "volume_level": self.tts_speak_volume}))
                _post_tts_actions.append(("media_player", "volume_set",
                    {"entity_id": mute_entity, "volume_level": 0.0}))
                _post_tts_actions.append(("media_player", "volume_mute",
                    {"entity_id": mute_entity, "is_volume_muted": True}))

        try:
            # ── Pre-TTS: prepare speaker for speaking ──
            for domain, service, data in _pre_tts_actions:
                await self.hass.services.async_call(domain, service, data, blocking=True)
            if _pre_tts_actions:
                await asyncio.sleep(0.3)

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
            if _post_tts_actions and self.tts_mute_after:
                # Estimate speech duration: ~5 chars/sec + per-pause + base
                clean = text.replace(" ", "").replace("\n", "")
                char_count = len(clean)
                pause_count = text.count(",") + text.count("。") + text.count("!") + text.count("?") + text.count(";")
                delay_ms = max(1000, char_count * 200 + pause_count * 300 + 500)
                _LOGGER.debug("TTS mute delay: %d ms for %d chars", delay_ms, char_count)
                await asyncio.sleep(delay_ms / 1000)
                # Re-mute (reverse order for switches first, then volume)
                for domain, service, data in reversed(_post_tts_actions):
                    await self.hass.services.async_call(domain, service, data, blocking=True)

        except Exception as exc:
            _LOGGER.error("TTS failed for %s: %s", tts_entity, exc)

    # ------------------------------------------------------------------
    # Storage (Persistence)
    # ------------------------------------------------------------------

    async def _async_load_storage(self) -> None:
        """Load persisted data (dynamic automations) from .storage."""
        stored = await self._store.async_load()
        if stored is None and self._legacy_store is not None:
            # First load with per-instance key: migrate legacy shared storage
            legacy = await self._legacy_store.async_load()
            if legacy:
                _LOGGER.info(
                    "Migrating storage from legacy shared key to per-instance key"
                )
                stored = legacy
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

        # Restore last input states (for duplicate/phantom detection across restarts)
        self._last_states.update(stored.get("last_input_states", {}))

    async def _async_save_storage(self) -> None:
        """Save dynamic automations and conversation history to .storage."""
        history_data = [msg.to_dict() for msg in self._history[-50:]]
        data = {
            "automations": [
                auto.to_dict() for auto in self._automations.values()
            ],
            "history": history_data,
            "last_input_states": dict(self._last_states),
        }
        _LOGGER.info("Saving storage: %d automations, %d history messages",
                     len(data["automations"]), len(history_data))
        await self._store.async_save(data)
