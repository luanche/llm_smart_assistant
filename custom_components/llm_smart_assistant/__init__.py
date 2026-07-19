"""LLM Smart Assistant integration for Home Assistant.

A custom integration that bridges OpenAI-compatible LLMs with Home Assistant,
enabling natural language control, dynamic automations, and TTS output.
"""

from __future__ import annotations

import asyncio
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

_LOGGER = logging.getLogger(__name__)

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

    # Remove chat panel
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


async def _async_register_services(
    hass: HomeAssistant, coordinator: LLMSmartAssistantCoordinator
) -> None:
    """Register custom services for this integration."""


    async def async_process_input(call):
        """Handle the process_input service call."""
        text = call.data.get("text", "")
        entry_filter = call.data.get("entry_id", "")
        if text:
            # If entry_filter is set, only process if it matches this instance
            if entry_filter and entry_filter != entry.entry_id:
                return
            await coordinator._async_process_user_input(
                "service_call", text
            )

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
        result = {
            "automations": [
                {
                    "automation_id": a.automation_id,
                    "entity_id": a.entity_id,
                    "condition": a.condition,
                    "description": a.description,
                }
                for a in automations
            ],
            "count": len(automations),
        }
        _LOGGER.debug("get_automations returning: %s", result)
        return result

    # Register services
    hass.services.async_register(
        DOMAIN,
        "process_input",
        async_process_input,
        schema=vol.Schema(
            {
                vol.Required("text"): cv.string,
                vol.Optional("entry_id", default=""): cv.string,
            }
        ),
    )

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
            html_content = await hass.async_add_executor_job(
                lambda: html_path.read_text(encoding="utf-8")
            )

            class ChatPanelView(HomeAssistantView):
                """Serve the AI Chat panel HTML."""
                url = "/api/llm_smart_assistant/chat_panel"
                name = "api:llm_smart_assistant:chat_panel"
                requires_auth = False

                async def get(self, request):
                    return web.Response(
                        text=html_content,
                        content_type="text/html",
                    )

            hass.http.register_view(ChatPanelView)

            # Try to register a sidebar panel
            try:
                # Need to also register the JS file endpoint
                js_path = html_path.with_name("chat.js")
                js_content = await hass.async_add_executor_job(
                    lambda: js_path.read_text(encoding="utf-8")
                )

                class ChatJSView(HomeAssistantView):
                    """Serve the AI Chat panel JavaScript."""
                    url = "/api/llm_smart_assistant/chat_js"
                    name = "api:llm_smart_assistant:chat_js"
                    requires_auth = False

                    async def get(self, request):
                        return web.Response(
                            text=js_content,
                            content_type="application/javascript",
                            headers={"Cache-Control": "no-cache"},
                        )

                hass.http.register_view(ChatJSView)

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
