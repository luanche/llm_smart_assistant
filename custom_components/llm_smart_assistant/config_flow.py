"""Config and Options flows for the LLM Smart Assistant integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ALLOW_AUTOMATION,
    CONF_API_BASE_URL,
    CONF_API_KEY,
    CONF_DOMAINS_WHITELIST,
    CONF_ENTITIES_WHITELIST,
    CONF_HISTORY_COUNT,
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
    DEFAULT_ALLOW_AUTOMATION,
    DEFAULT_API_BASE_URL,
    DEFAULT_HISTORY_COUNT,
    DEFAULT_HISTORY_MODE,
    DEFAULT_HISTORY_TIME_WINDOW,
    DEFAULT_IGNORE_DUPLICATE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEFAULT_PROMPT_AUTOMATION,
    DEFAULT_PROMPT_DEFAULT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    HISTORY_MODE_COUNT,
    HISTORY_MODE_TIME,
    RESTRICTED_DOMAINS,
    TTS_MODE_CUSTOM,
    TTS_MODE_STANDARD,
    TTS_MODE_XIAOMI_MIOT,
)

_LOGGER = logging.getLogger(__name__)


async def validate_api_connection(
    hass: HomeAssistant,
    api_base_url: str,
    api_key: str,
    model_name: str,
) -> dict[str, str] | None:
    """Validate the LLM API connection by listing models.

    Returns a dict with errors if validation fails, or None on success.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{api_base_url.rstrip('/')}/models"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 401:
                    return {"base": "invalid_auth"}
                if resp.status == 404:
                    return None
                if resp.status != 200:
                    return {"base": "cannot_connect"}
                data = await resp.json()
                models = data.get("data", [])
                model_ids = [m.get("id") for m in models]
                if model_name not in model_ids and model_ids:
                    _LOGGER.warning(
                        "Model '%s' not found in provider's model list. Available: %s",
                        model_name,
                        ", ".join(model_ids[:10]),
                    )
                return None
    except aiohttp.ClientError as exc:
        _LOGGER.error("API connection error: %s", exc)
        return {"base": "cannot_connect"}
    except Exception as exc:
        _LOGGER.error("Unexpected error validating API: %s", exc)
        return {"base": "unknown"}


class LLMSmartAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for LLM Smart Assistant."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> LLMSmartAssistantOptionsFlow:
        """Return the options flow handler."""
        return LLMSmartAssistantOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step for API configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_base_url = user_input[CONF_API_BASE_URL].rstrip("/")
            api_key = user_input[CONF_API_KEY]
            model_name = user_input[CONF_MODEL_NAME]

            validation_errors = await validate_api_connection(
                self.hass, api_base_url, api_key, model_name
            )
            if validation_errors:
                errors.update(validation_errors)
            else:
                return self.async_create_entry(
                    title="LLM Smart Assistant",
                    data={
                        CONF_API_BASE_URL: api_base_url,
                        CONF_API_KEY: api_key,
                        CONF_MODEL_NAME: model_name,
                        CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
                        CONF_MAX_TOKENS: DEFAULT_MAX_TOKENS,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_API_BASE_URL, default=DEFAULT_API_BASE_URL
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type="url"),
                    ),
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type="password"),
                    ),
                    vol.Required(
                        CONF_MODEL_NAME, default=DEFAULT_MODEL_NAME
                    ): selector.TextSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "api_base_url": "https://api.openai.com/v1",
                "model_name": "gpt-4o-mini",
            },
        )


class LLMSmartAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle the options flow for LLM Smart Assistant."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Main configuration page with all options in one form."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Clean up empty values before saving
            for key in (CONF_TTS_ENTITY_ID,):
                if key in user_input and user_input[key] in ("", None):
                    user_input[key] = ""
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)

        current = self.config_entry.options
        current_data = self.config_entry.data

        # Build a comprehensive list of common HA domains for the whitelist
        common_domains = [
            "alarm_control_panel", "automation", "binary_sensor", "button",
            "camera", "climate", "cover", "device_tracker", "fan",
            "humidifier", "light", "lock", "media_player", "remote",
            "scene", "script", "sensor", "siren", "switch", "vacuum",
            "water_heater", "weather", "valve", "update", "lawn_mower",
            "conversation", "event", "todo", "tts", "sun",
        ]
        # Merge with existing domains from the system
        all_domains = set(common_domains)
        for state in self.hass.states.async_all():
            domain = state.entity_id.split(".")[0]
            if domain not in RESTRICTED_DOMAINS:
                all_domains.add(domain)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    # --- Prompts Section ---
                    vol.Optional(
                        CONF_PROMPT_DEFAULT,
                        default=current.get(
                            CONF_PROMPT_DEFAULT, DEFAULT_PROMPT_DEFAULT
                        ),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True),
                    ),
                    vol.Optional(
                        CONF_PROMPT_AUTOMATION,
                        default=current.get(
                            CONF_PROMPT_AUTOMATION, DEFAULT_PROMPT_AUTOMATION
                        ),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True),
                    ),
                    # --- Input Entities Section ---
                    vol.Optional(
                        CONF_INPUT_ENTITIES,
                        default=current.get(CONF_INPUT_ENTITIES, []),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["sensor"], multiple=True
                        ),
                    ),
                    vol.Optional(
                        CONF_IGNORE_DUPLICATE,
                        default=current.get(
                            CONF_IGNORE_DUPLICATE, DEFAULT_IGNORE_DUPLICATE
                        ),
                    ): selector.BooleanSelector(),
                    # --- LLM Parameters Section ---
                    vol.Optional(
                        CONF_TEMPERATURE,
                        default=current_data.get(
                            CONF_TEMPERATURE, DEFAULT_TEMPERATURE
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.0, max=2.0, step=0.1,
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                    vol.Optional(
                        CONF_MAX_TOKENS,
                        default=current_data.get(
                            CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=64, max=32768, step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                    # --- TTS Section ---
                    vol.Optional(
                        CONF_TTS_ENTITY_ID,
                        default=current.get(CONF_TTS_ENTITY_ID) or "",
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type="text"),
                    ),
                    vol.Optional(
                        CONF_TTS_MODE,
                        default=current.get(CONF_TTS_MODE, TTS_MODE_STANDARD),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                TTS_MODE_STANDARD,
                                TTS_MODE_XIAOMI_MIOT,
                                TTS_MODE_CUSTOM,
                            ],
                            translation_key="tts_mode",
                        ),
                    ),
                    vol.Optional(
                        CONF_TTS_CUSTOM_TEMPLATE,
                        default=current.get(CONF_TTS_CUSTOM_TEMPLATE, ""),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True),
                    ),
                    # --- Security Section ---
                    vol.Optional(
                        CONF_DOMAINS_WHITELIST,
                        default=current.get(
                            CONF_DOMAINS_WHITELIST,
                            ["light", "switch", "media_player"],
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=sorted(all_domains),
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        ),
                    ),
                    vol.Optional(
                        CONF_ENTITIES_WHITELIST,
                        default=current.get(CONF_ENTITIES_WHITELIST, []),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(multiple=True),
                    ),
                    vol.Optional(
                        CONF_ALLOW_AUTOMATION,
                        default=current.get(
                            CONF_ALLOW_AUTOMATION, DEFAULT_ALLOW_AUTOMATION
                        ),
                    ): selector.BooleanSelector(),
                    # --- History Section ---
                    vol.Optional(
                        CONF_HISTORY_MODE,
                        default=current.get(
                            CONF_HISTORY_MODE, DEFAULT_HISTORY_MODE
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[HISTORY_MODE_COUNT, HISTORY_MODE_TIME],
                            translation_key="history_mode",
                        ),
                    ),
                    vol.Optional(
                        CONF_HISTORY_COUNT,
                        default=current.get(
                            CONF_HISTORY_COUNT, DEFAULT_HISTORY_COUNT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=100, step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        ),
                    ),
                    vol.Optional(
                        CONF_HISTORY_TIME_WINDOW,
                        default=current.get(
                            CONF_HISTORY_TIME_WINDOW, DEFAULT_HISTORY_TIME_WINDOW
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=1440, step=1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="minutes",
                        ),
                    ),
                }
            ),
            errors=errors,
        )
