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
from typing import Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv

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

    # Remove chat panel only when the last instance is removed
    if not hass.data.get(DOMAIN):
        try:
            frontend.async_remove_panel(hass, "llm-chat")
        except Exception:
            pass

    return True


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

        if entity_id and condition:
            await coordinator.async_create_automation(
                entity_id=entity_id,
                condition=condition,
                prompt=prompt,
                description=description,
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
                    "description": a.description,
                    "prompt": a.prompt,
                    "disabled": a.automation_id in disabled_set,
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
                vol.Required("entity_id"): cv.string,
                vol.Required("condition"): cv.string,
                vol.Optional("prompt"): cv.string,
                vol.Optional("description"): cv.string,
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
        
        for c in hass.data.get(DOMAIN, {}).values():
            coord = c
            if automation_id in coord._automations:
                auto = coord._automations[automation_id]
                needs_relisten = False
                if prompt:
                    auto.prompt = prompt
                if description:
                    auto.description = description
                if entity_id:
                    auto.entity_id = entity_id
                    needs_relisten = True
                if condition:
                    auto.condition = condition
                    needs_relisten = True
                
                if needs_relisten:
                    # Remove old listener and register new one
                    old_listener = coord._automation_listeners.pop(automation_id, None)
                    if old_listener:
                        old_listener()
                    from homeassistant.helpers.event import async_track_state_change_event
                    remove_listener = async_track_state_change_event(
                        coord.hass,
                        auto.entity_id,
                        lambda event: coord._async_handle_automation_event(auto, event),
                    )
                    coord._automation_listeners[automation_id] = remove_listener
                    _LOGGER.info("Re-registered listener for automation '%s' -> %s %s", automation_id, auto.entity_id, auto.condition)
                
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



                # Only register the sidebar panel once (on first entry)
                if not hass.data.get(DOMAIN) or len(hass.data[DOMAIN]) <= 1:
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
                    panel_err
                )
                _LOGGER.info(
                    "Chat UI available at http://localhost:8123/api/llm_smart_assistant/chat_panel"
                )
        else:
            _LOGGER.warning("Chat panel HTML not found at %s", html_path)
    except Exception as exc:
        _LOGGER.warning("Chat panel setup error: %s", exc)
