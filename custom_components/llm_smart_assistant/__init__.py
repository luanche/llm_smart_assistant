"""LLM Smart Assistant integration for Home Assistant.

A custom integration that bridges OpenAI-compatible LLMs with Home Assistant,
enabling natural language control, dynamic automations, and TTS output.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import pathlib
from datetime import timedelta
from typing import Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DOMAIN, CONF_TEMPERATURE, CONF_MAX_TOKENS, CONF_API_BASE_URL, CONF_API_KEY, CONF_MODEL_NAME
from .coordinator import LLMSmartAssistantCoordinator
from .services import ServicesExecutor

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

# Module-level cache for suggestions (avoids class-variable scoping issues in dynamic views)
_SUGGESTIONS_CACHE: dict[str, dict[str, Any]] = {}



PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the LLM Smart Assistant integration via YAML (if needed)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LLM Smart Assistant from a config entry."""
    _LOGGER.info("Setting up LLM Smart Assistant integration")

    # Create the core coordinator
    coordinator = LLMSmartAssistantCoordinator(
        hass=hass,
        config_entry_data=dict(entry.data),
        config_entry_options=dict(entry.options),
        entry_id=entry.entry_id,
    )

    # Create the services executor and link it to the coordinator
    executor = ServicesExecutor(hass=hass, coordinator=coordinator)
    coordinator.executor = executor

    # Store coordinator in hass.data BEFORE forwarding setups
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register services
    await _async_register_services(hass, coordinator)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Start the coordinator (loads storage, registers listeners)
    await coordinator.async_start()

    # Forward to sensor platform (calls sensor.py async_setup_entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register chat panel
    await _async_register_chat_panel(hass, coordinator)

    _LOGGER.info("LLM Smart Assistant setup completed")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading LLM Smart Assistant integration")

    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_unload()

    hass.data[DOMAIN].pop(entry.entry_id, None)

    # Sync sidebar panel: remove it when no instance shows it anymore
    await _async_sync_chat_panel(hass)

    return True


async def _async_sync_chat_panel(hass: HomeAssistant) -> None:
    """Register or remove the AI Chat sidebar panel based on all instances.

    Panel is shown if ANY instance has show_panel enabled; removed only when
    every instance disables it. Keeps the panel registered exactly once even
    with multiple config entries.
    """
    any_show = any(
        getattr(coord, "show_panel", True)
        for coord in hass.data.get(DOMAIN, {}).values()
    )
    try:
        panel_exists = frontend.async_panel_exists(hass, "llm-chat")
    except Exception:
        panel_exists = False

    if any_show and not panel_exists:
        try:
            await panel_custom.async_register_panel(
                hass=hass,
                frontend_url_path="llm-chat",
                webcomponent_name="llm-chat-panel",
                sidebar_title="AI Chat",
                sidebar_icon="mdi:robot",
                module_url="/api/llm_smart_assistant/chat_js",
                require_admin=True,
                config={},
            )
            _LOGGER.info("AI Chat panel registered in sidebar at /llm-chat")
        except Exception as panel_err:
            _LOGGER.warning(
                "Sidebar panel registration failed (you can still open the chat directly): %s",
                panel_err,
            )
    elif not any_show and panel_exists:
        try:
            frontend.async_remove_panel(hass, "llm-chat")
            _LOGGER.info("AI Chat panel removed from sidebar (all instances disabled)")
        except Exception:
            pass


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update. Sync params from options to data."""
    sync_keys = [
        CONF_TEMPERATURE, CONF_MAX_TOKENS,
        CONF_API_BASE_URL, CONF_API_KEY, CONF_MODEL_NAME,
    ]
    needs_data_update = any(k in entry.options for k in sync_keys)

    if needs_data_update:
        # Move sync keys from options to data, keep others in options
        new_data = {**dict(entry.data)}
        new_options = {}
        for k, v in entry.options.items():
            if k in sync_keys:
                new_data[k] = v
            else:
                new_options[k] = v
        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options
        )
        _LOGGER.debug("Synced LLM parameters from options to data")

    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_update_config(
            new_data=dict(entry.data),
            new_options=dict(entry.options),
        )
        _LOGGER.debug("Configuration updated for LLM Smart Assistant")

    # Sync sidebar panel visibility (show_panel option may have changed)
    await _async_sync_chat_panel(hass)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to a newer version if needed."""
    _LOGGER.debug(
        "Migrating config entry from version %s", entry.version
    )
    return True


def _register_global_services(hass: HomeAssistant) -> None:
    """Register shared services that work across all instances."""
    
    # Only register once
    if hass.services.has_service(DOMAIN, "process_input"):
        return

    async def async_process_input(call):
        """Handle the process_input service call."""
        text = call.data.get("text", "")
        source = call.data.get("source", "")  # 'voice' from chat UI voice input
        entry_filter = call.data.get("entry_id", "")
        if text:
            if entry_filter:
                # Look up the coordinator for this instance
                coordinator = hass.data.get(DOMAIN, {}).get(entry_filter)
                if coordinator:
                    await coordinator._async_process_user_input("service_call", text, source)
                else:
                    _LOGGER.warning("No coordinator found for entry %s", entry_filter)
            else:
                # No filter: process on all instances
                for coordinator in hass.data.get(DOMAIN, {}).values():
                    await coordinator._async_process_user_input("service_call", text, source)

    hass.services.async_register(
        DOMAIN,
        "process_input",
        async_process_input,
        schema=vol.Schema(
            {
                vol.Optional("text", default=""): cv.string,
                vol.Optional("entry_id", default=""): cv.string,
                vol.Optional("source", default=""): cv.string,
            }
        ),
    )
    _LOGGER.info("Global process_input service registered")

    # Also register toggle_automation globally
    if not hass.services.has_service(DOMAIN, "toggle_automation"):
        
        async def async_toggle_automation(call):
            """Enable or disable a dynamic automation (adds/removes listener)."""
            automation_id = call.data.get("automation_id", "")
            disable = call.data.get("disable", True)
            entry_filter = call.data.get("entry_id", "")
            
            _LOGGER.info("toggle_automation: id=%s disable=%s entry=%s", automation_id, disable, entry_filter)
            
            for eid, coord in hass.data.get(DOMAIN, {}).items():
                if entry_filter and eid != entry_filter:
                    continue
                if automation_id not in coord._automations:
                    _LOGGER.warning("Automation '%s' not found in entry %s", automation_id, eid)
                    continue
                if disable:
                    await coord.async_disable_automation(automation_id)
                else:
                    await coord.async_enable_automation(automation_id)
        
        hass.services.async_register(
            DOMAIN,
            "toggle_automation",
            async_toggle_automation,
            schema=vol.Schema({
                vol.Required("automation_id"): cv.string,
                vol.Optional("disable", default=True): cv.boolean,
                vol.Optional("entry_id", default=""): cv.string,
            }),
        )
        _LOGGER.info("Global toggle_automation service registered")


async def _async_register_services(
    hass: HomeAssistant, coordinator: LLMSmartAssistantCoordinator
) -> None:
    """Register custom services for this integration."""
    
    _register_global_services(hass)

    async def async_create_automation(call):
        """Handle the create_automation service call."""
        entity_id = call.data.get("entity_id", "")
        condition = call.data.get("condition", "")
        prompt = call.data.get("prompt", "")
        description = call.data.get("description", "")
        triggers = call.data.get("triggers")
        trigger_logic = call.data.get("trigger_logic", "or")
        one_shot = call.data.get("one_shot", False)
        expression = call.data.get("expression", "")

        if triggers or (entity_id and condition):
            await coordinator.async_create_automation(
                entity_id=entity_id,
                condition=condition,
                prompt=prompt,
                description=description,
                triggers=triggers,
                trigger_logic=trigger_logic,
                one_shot=bool(one_shot),
                expression=expression,
            )

    async def async_remove_automation(call):
        """Handle the remove_automation service call."""
        automation_id = call.data.get("automation_id", "")
        if automation_id:
            await coordinator.async_remove_automation(automation_id)

    async def async_get_automations(call):
        """Handle the get_automations service call."""
        automations = list(coordinator._automations.values())
        disabled_set = coordinator._disabled_automations_set
        result = {
            "automations": [
                {
                    "automation_id": a.automation_id,
                    "entity_id": a.entity_id,
                    "condition": a.condition,
                    "triggers": a.triggers,
                    "trigger_logic": a.trigger_logic,
                    "expression": a.expression,
                    "description": a.description,
                    "prompt": a.prompt,
                    "one_shot": a.one_shot,
                    "disabled": a.automation_id in disabled_set,
                    "records": a.records[-10:],  # recent records for debug UI
                }
                for a in automations
            ],
            "count": len(automations),
            "disabled_ids": list(disabled_set),
        }
        _LOGGER.debug("get_automations returning: %s", result)
        return result

    # Register services
    hass.services.async_register(
        DOMAIN,
        "create_automation",
        async_create_automation,
        schema=vol.Schema(
            {
                vol.Optional("entity_id"): cv.string,
                vol.Optional("condition"): cv.string,
                vol.Optional("prompt"): cv.string,
                vol.Optional("description"): cv.string,
                vol.Optional("triggers"): list,
                vol.Optional("trigger_logic"): cv.string,
                vol.Optional("one_shot"): bool,
                vol.Optional("expression"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "remove_automation",
        async_remove_automation,
        schema=vol.Schema(
            {
                vol.Required("automation_id"): cv.string,
            }
        ),
    )

    async def async_update_automation(call):
        """Update an automation's fields and re-register listener if needed."""
        automation_id = call.data.get("automation_id", "")
        prompt = call.data.get("prompt", "")
        description = call.data.get("description", "")
        entity_id = call.data.get("entity_id", "")
        condition = call.data.get("condition", "")
        triggers = call.data.get("triggers")
        trigger_logic = call.data.get("trigger_logic", "")
        one_shot = call.data.get("one_shot")
        expression = call.data.get("expression")
        
        for c in hass.data.get(DOMAIN, {}).values():
            coord = c
            if automation_id in coord._automations:
                auto = coord._automations[automation_id]
                needs_relisten = False
                if prompt:
                    auto.prompt = prompt
                if description is not None:
                    auto.description = description
                if triggers is not None:
                    auto.triggers = [
                        t for t in triggers if t.get("entity_id") or t.get("time")
                    ]
                    needs_relisten = True
                elif entity_id or condition:
                    # Legacy single-field update: replace the first trigger
                    if auto.triggers:
                        if entity_id:
                            auto.triggers[0]["entity_id"] = entity_id
                        if condition is not None:
                            auto.triggers[0]["condition"] = condition
                    else:
                        auto.triggers = [
                            {"entity_id": entity_id, "condition": condition}
                        ]
                    needs_relisten = True
                if trigger_logic in ("and", "or"):
                    auto.trigger_logic = trigger_logic
                if expression is not None:
                    auto.expression = expression or ""
                if one_shot is not None:
                    auto.one_shot = bool(one_shot)
                
                if needs_relisten:
                    coord._unregister_automation_listener(automation_id)
                    coord._register_automation_listener(auto)
                    _LOGGER.info(
                        "Re-registered listener for automation '%s' -> %d triggers (expr=%s)",
                        automation_id, len(auto.triggers), auto.expression or auto.trigger_logic,
                    )
                
                await coord._async_save_storage()
                _LOGGER.info("Updated automation '%s'", automation_id)
                break
    
    hass.services.async_register(
        DOMAIN,
        "update_automation",
        async_update_automation,
        schema=vol.Schema({
            vol.Required("automation_id"): cv.string,
            vol.Optional("prompt"): cv.string,
            vol.Optional("description"): cv.string,
            vol.Optional("entity_id"): cv.string,
            vol.Optional("condition"): cv.string,
            vol.Optional("triggers"): list,
            vol.Optional("trigger_logic"): cv.string,
            vol.Optional("one_shot"): bool,
            vol.Optional("expression"): cv.string,
        }),
    )

    # toggle_automation is registered globally (see _register_global_services)

    hass.services.async_register(
        DOMAIN,
        "get_automations",
        async_get_automations,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.OPTIONAL,
    )

    _LOGGER.debug("Registered LLM Smart Assistant services")


async def _async_register_chat_panel(
    hass: HomeAssistant,
    coordinator: LLMSmartAssistantCoordinator,
) -> None:
    """Register the AI Chat panel and chat service."""

    # 1. Register chat service (returns the LLM response)
    async def async_chat(call):
        """Handle the chat service call - returns LLM response."""
        text = call.data.get("text", "")
        if not text:
            return {"error": "text is required"}

        # Process input and wait for response
        await coordinator._async_process_user_input("chat_ui", text)

        # Give a short moment for the response to be stored
        await asyncio.sleep(0.5)

        if coordinator.last_response:
            return {
                "tts_text": coordinator.last_response.get("tts_text", ""),
                "steps": coordinator.last_response.get("steps", []),
                "raw": coordinator.last_response_raw,
            }
        return {"error": "No response yet", "raw": coordinator.last_response_raw}

    hass.services.async_register(
        DOMAIN,
        "chat",
        async_chat,
        schema=vol.Schema({
            vol.Required("text"): cv.string,
        }),
    )

    _LOGGER.debug("Registered LLM Smart Assistant chat service")

    # 2. Register the AI Chat panel via HTTP view
    try:
        panel_dir = pathlib.Path(hass.config.path("custom_components/llm_smart_assistant/panel"))
        html_path = panel_dir / "index.html"

        if html_path.is_file():
            class ChatPanelView(HomeAssistantView):
                """Serve the AI Chat panel HTML."""
                url = "/api/llm_smart_assistant/chat_panel"
                name = "api:llm_smart_assistant:chat_panel"
                requires_auth = False

                async def get(self, request):
                    # Read fresh on each request so edits take effect without restart
                    current_html = await hass.async_add_executor_job(
                        lambda: html_path.read_text(encoding="utf-8")
                    )
                    # Inject configured access token (if any) into the HTML
                    access_token = ""
                    for coord in hass.data.get(DOMAIN, {}).values():
                        if hasattr(coord, 'access_token') and coord.access_token:
                            access_token = coord.access_token
                            break
                    if access_token:
                        script = f'<script>window.CONFIGURED_ACCESS_TOKEN={json.dumps(access_token)};</script>'
                        current_html = current_html.replace("</head>", script + "</head>")
                    # Inject per-instance info: title + sensor entity_ids so the
                    # panel can subscribe to the right sensors for multi-instance setups
                    try:
                        er = async_get_entity_registry(hass)
                        instances = []
                        for eid, coord in hass.data.get(DOMAIN, {}).items():
                            if not hasattr(coord, 'access_token'):
                                continue
                            last_resp = er.async_get_entity_id("sensor", DOMAIN, f"{eid}_last_response")
                            debug_raw = er.async_get_entity_id("sensor", DOMAIN, f"{eid}_debug_raw")
                            last_input = er.async_get_entity_id("sensor", DOMAIN, f"{eid}_last_input")
                            instances.append({
                                "entry_id": eid,
                                "title": getattr(coord, 'title', '') or '',
                                "last_response": last_resp or "",
                                "debug_raw": debug_raw or "",
                                "last_input": last_input or "",
                                "show_panel": getattr(coord, 'show_panel', True),
                            })
                        if instances:
                            inst_script = (
                                '<script>window.CONFIGURED_INSTANCES='
                                + json.dumps(instances, ensure_ascii=False)
                                + ';</script>'
                            )
                            current_html = current_html.replace("</head>", inst_script + "</head>")
                    except Exception:
                        _LOGGER.debug("Failed to inject instance info", exc_info=True)
                    return web.Response(
                        text=current_html,
                        content_type="text/html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                    )

            hass.http.register_view(ChatPanelView)

            # Try to register a sidebar panel
            try:
                # Need to also register the JS file endpoint
                class ChatJSView(HomeAssistantView):
                    """Serve the AI Chat panel JavaScript."""
                    url = "/api/llm_smart_assistant/chat_js"
                    name = "api:llm_smart_assistant:chat_js"
                    requires_auth = False

                    async def get(self, request):
                        current_js = await hass.async_add_executor_job(
                            lambda: html_path.with_name("chat.js").read_text(encoding="utf-8")
                        )
                        return web.Response(
                            text=current_js,
                            content_type="application/javascript",
                            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                        )

                hass.http.register_view(ChatJSView)

                # Suggestions API - generates smart suggestions based on user's devices
                # Supports two URL forms:
                #   /api/llm_smart_assistant/suggestions?entry_id=xxx
                #   /api/llm_smart_assistant/{entry_id}/suggestions  (path-based, for clarity)
                class ChatSuggestionsView(HomeAssistantView):
                    """Generate chat suggestions based on exposed entities."""
                    url = "/api/llm_smart_assistant/suggestions"
                    name = "api:llm_smart_assistant:suggestions"
                    requires_auth = False

                    async def get(self, request):
                        entry_id = request.query.get("entry_id", "")
                        # Also try path-based entry_id from /api/llm_smart_assistant/{entry_id}/suggestions
                        path_parts = request.path.strip("/").split("/")
                        if len(path_parts) == 4 and path_parts[3] == "suggestions":
                            entry_id = entry_id or path_parts[2]

                        coordinator = None
                        if entry_id and entry_id in hass.data.get(DOMAIN, {}):
                            coordinator = hass.data[DOMAIN][entry_id]
                        else:
                            for eid, coord in hass.data.get(DOMAIN, {}).items():
                                if hasattr(coord, 'domains_whitelist'):
                                    coordinator = coord
                                    entry_id = eid
                                    break

                        if not coordinator:
                            return web.json_response({
                                "suggestions": [],
                                "hash": ""
                            })

                        # Build cache key from entity configuration
                        domains = sorted(coordinator.domains_whitelist or [])
                        entities = sorted(coordinator.entities_whitelist or [])
                        cache_key = hashlib.md5(
                            ("".join(domains) + "|" + "".join(entities)).encode()
                        ).hexdigest()[:16]

                        cached = _SUGGESTIONS_CACHE.get(entry_id, {})
                        if cached.get("hash") == cache_key:
                            return web.json_response({
                                "suggestions": cached["suggestions"],
                                "hash": cache_key,
                            })

                        # Build entity context for LLM
                        entity_csv = coordinator._build_entity_csv()
                        # Use HA user's configured language
                        user_lang = (hass.config.language or "en").split("-")[0]
                        lang_name = {"zh": "Chinese", "en": "English", "ja": "Japanese", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese", "ko": "Korean", "ru": "Russian"}.get(user_lang, "English")
                        prompt_text = (
                            f"Based on these smart home devices:\n{entity_csv}\n\n"
                            f"Generate 4 short example commands in {lang_name} that a user might ask. "
                            f"Mix device control and info queries. Use real device names. "
                            f"Output each command on its own line, no numbering, no extra text."
                        )

                        try:
                            raw = await coordinator._async_query_llm_raw([{
                                "role": "system",
                                "content": f"You are a smart home assistant. Generate example commands in {lang_name}."
                            }, {
                                "role": "user",
                                "content": prompt_text
                            }], max_tokens=300)
                            if raw:
                                lines = [s.strip() for s in raw.split("\n") if s.strip()]
                                result = lines[:6]
                                _SUGGESTIONS_CACHE[entry_id] = {
                                    "hash": cache_key,
                                    "suggestions": result,
                                }
                                return web.json_response({
                                    "suggestions": result,
                                    "hash": cache_key,
                                })
                        except Exception:
                            pass

                        return web.json_response({
                            "suggestions": cached.get("suggestions", []),
                            "hash": cache_key,
                        })

                # Register main suggestions endpoint
                hass.http.register_view(ChatSuggestionsView)

                # Chat history API — reads HA recorder history for the selected
                # instance's last-response sensor + input sensors, merged into a
                # unified timeline. Lazy-paginated via the `before` cursor.
                class ChatHistoryView(HomeAssistantView):
                    """Serve merged chat history for the selected instance."""
                    url = "/api/llm_smart_assistant/history"
                    name = "api:llm_smart_assistant:history"
                    requires_auth = False

                    async def get(self, request):
                        entry_id = request.query.get("entry_id", "")
                        before_raw = request.query.get("before", "")
                        try:
                            limit = min(int(request.query.get("limit", "20")), 50)
                        except ValueError:
                            limit = 20

                        # Resolve coordinator
                        coordinator = None
                        if entry_id and entry_id in hass.data.get(DOMAIN, {}):
                            coordinator = hass.data[DOMAIN][entry_id]
                        else:
                            for eid, coord in hass.data.get(DOMAIN, {}).items():
                                if hasattr(coord, 'access_token'):
                                    coordinator = coord
                                    entry_id = eid
                                    break
                        if not coordinator:
                            return web.json_response({"items": [], "has_more": False})

                        # Parse before cursor (ISO string, default now)
                        end_time = dt_util.now()
                        if before_raw:
                            parsed = dt_util.parse_datetime(before_raw)
                            if parsed:
                                # Subtract a tiny epsilon so the boundary record
                                # (same timestamp as the cursor) is not repeated
                                end_time = parsed - timedelta(microseconds=1)
                            else:
                                # Unparseable cursor: return empty to avoid loops
                                return web.json_response({"items": [], "has_more": False})
                        start_time = end_time - timedelta(days=7)

                        # Entity IDs to query: last-response sensor + last-input
                        # sensor (covers ALL input sources: chat panel, service
                        # calls, and voice input sensors)
                        try:
                            er = async_get_entity_registry(hass)
                            resp_sensor = er.async_get_entity_id(
                                "sensor", DOMAIN, f"{entry_id}_last_response"
                            )
                            input_sensor = er.async_get_entity_id(
                                "sensor", DOMAIN, f"{entry_id}_last_input"
                            )
                        except Exception:
                            resp_sensor = None
                            input_sensor = None
                        if not resp_sensor:
                            resp_sensor = "sensor.llm_last_response"
                        if not input_sensor:
                            input_sensor = "sensor.llm_last_input"
                        entity_ids = [resp_sensor, input_sensor]

                        items: list[dict[str, Any]] = []
                        try:
                            from homeassistant.components.recorder import get_instance
                            from homeassistant.components.recorder.history import get_significant_states

                            _LOGGER.debug(
                                "History query: entities=%s start=%s end=%s",
                                entity_ids, start_time.isoformat(), end_time.isoformat(),
                            )
                            rows = await get_instance(hass).async_add_executor_job(
                                get_significant_states,
                                hass,
                                start_time,
                                end_time,
                                entity_ids,
                                None,  # filters
                                False,  # include_start_time_state: skip initial snapshot
                            )
                            _LOGGER.debug("History rows: %s", {k: len(v) for k, v in (rows or {}).items()})
                            raw_items: list[dict[str, Any]] = []
                            for ent_id, states in (rows or {}).items():
                                states_sorted = sorted(states, key=lambda s: s.last_changed)
                                for st in states_sorted:
                                    text = (st.state or "").strip()
                                    if not text or text in ("unavailable", "unknown"):
                                        continue
                                    raw_items.append({
                                        "role": "assistant" if ent_id == resp_sensor else "user",
                                        "text": text,
                                        "time": st.last_changed,
                                        "entity": ent_id,
                                        # Every assistant reply records the user input
                                        # it responded to — use it as the grouping key
                                        "reply_to": (st.attributes.get("last_input") or "").strip()
                                        if ent_id == resp_sensor else "",
                                    })

                            # Merge into a clean conversation: group assistant rounds by
                            # the user message they replied to (using the reply_to
                            # attribute), then keep only the LAST distinct text of each
                            # group. This is robust against timestamp skew between the
                            # user-input sensor and the reply sensor.
                            raw_items.sort(key=lambda x: x["time"])
                            _LOGGER.debug(
                                "History raw: %s",
                                [(r["role"], r["text"][:15], r["time"].strftime("%H:%M:%S.%f")) for r in raw_items],
                            )
                            merged: list[dict[str, Any]] = []
                            # map: user_text -> final assistant record of that group
                            assistant_by_input: dict[str, dict[str, Any]] = {}
                            for r in raw_items:
                                if r["role"] == "user":
                                    merged.append(r)
                                else:
                                    key = r["reply_to"] or r["text"]
                                    prev = assistant_by_input.get(key)
                                    if prev is None:
                                        assistant_by_input[key] = dict(r)
                                    elif r["text"] != prev["text"]:
                                        assistant_by_input[key] = dict(r)

                            # Insert each assistant reply right after its user message
                            final: list[dict[str, Any]] = []
                            for m in merged:
                                final.append(m)
                                if m["role"] == "user":
                                    reply = assistant_by_input.pop(m["text"], None)
                                    if reply:
                                        final.append(reply)
                            # Any assistant replies without a matching user message in
                            # this window (e.g. history started mid-conversation)
                            for reply in assistant_by_input.values():
                                final.append(reply)
                            merged = final

                            _LOGGER.debug(
                                "History merged: %s",
                                [(m["role"], m["text"][:20], m["time"].strftime("%H:%M:%S.%f")) for m in merged],
                            )

                            items = [
                                {
                                    "role": m["role"],
                                    "text": m["text"],
                                    "time": m["time"].isoformat(),
                                    "entity": m["entity"],
                                }
                                for m in merged
                            ]
                        except Exception as exc:
                            _LOGGER.debug("History query failed: %s", exc)

                        # Newest first, then page
                        items.sort(key=lambda x: x["time"], reverse=True)
                        page = items[:limit]
                        has_more = len(items) > limit
                        return web.json_response({"items": page, "has_more": has_more})

                hass.http.register_view(ChatHistoryView)



                # Register the sidebar panel based on all instances' show_panel settings
                await _async_sync_chat_panel(hass)
            except Exception as panel_err:
                _LOGGER.warning(
                    "Sidebar panel registration failed (you can still open the chat directly): %s",
                    panel_err
                )
                _LOGGER.info(
                    "Chat UI available at http://localhost:8123/api/llm_smart_assistant/chat_panel"
                )
        else:
            _LOGGER.warning("Chat panel HTML not found at %s", html_path)
    except Exception as exc:
        _LOGGER.warning("Chat panel setup error: %s", exc)
