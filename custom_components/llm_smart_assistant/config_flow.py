"""Config and Options flows for the LLM Smart Assistant integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_ACCESS_TOKEN,
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
    DEFAULT_ALLOW_AUTOMATION,
    DEFAULT_API_BASE_URL,
    DEFAULT_HISTORY_COUNT,
    DEFAULT_HISTORY_ENABLED,
    DEFAULT_HISTORY_MODE,
    DEFAULT_HISTORY_TIME_WINDOW,
    DEFAULT_IGNORE_DUPLICATE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_NAME,
    DEFAULT_PROMPT_AUTOMATION,
    DEFAULT_PROMPT_DEFAULT,
    DEFAULT_TEMPERATURE,
    DEFAULT_TTS_SPEAK_VOLUME,
    DEFAULT_TTS_MUTE_AFTER,
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
    """Validate the LLM API connection.

    Probe 1: GET /models (OpenAI standard). Some providers (e.g. Databricks
    serving endpoints) do not expose /models and return 403/404 — in that
    case fall back to probe 2: a minimal POST /chat/completions.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base = api_base_url.rstrip("/")
    # Probe 2 needs a generous timeout: serverless endpoints (e.g. Databricks)
    # can take 60s+ to cold-start the model.
    probe_timeout = aiohttp.ClientTimeout(total=15)
    chat_timeout = aiohttp.ClientTimeout(total=90)
    try:
        async with aiohttp.ClientSession() as session:
            # Probe 1: GET /models
            async with session.get(
                f"{base}/models", headers=headers, timeout=probe_timeout
            ) as resp:
                if resp.status == 401:
                    return {"base": "invalid_auth"}
                if resp.status == 200:
                    return None
                if resp.status not in (403, 404):
                    return {"base": "cannot_connect"}
                # 403/404: provider doesn't expose /models — try probe 2

            # Probe 2: minimal chat completion
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }
            async with session.post(
                f"{base}/chat/completions", headers=headers, json=payload,
                timeout=chat_timeout,
            ) as resp:
                if resp.status == 401:
                    return {"base": "invalid_auth"}
                if resp.status == 404:
                    return {"base": "invalid_model"}
                if resp.status != 200:
                    return {"base": "cannot_connect"}
                return None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("API validation failed with unexpected error")
        return {"base": "unknown"}


class _OptionalEntitySelector(selector.EntitySelector):
    """EntitySelector that accepts empty string (optional field)."""

    def __call__(self, data: Any) -> str | list[str]:
        if not data:
            return ""
        return super().__call__(data)


class LLMSmartAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LLMSmartAssistantOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            title = user_input.pop("title", "LLM Smart Assistant")
            api_base_url = user_input[CONF_API_BASE_URL].rstrip("/")
            api_key = user_input[CONF_API_KEY]
            model_name = user_input[CONF_MODEL_NAME]
            errs = await validate_api_connection(
                self.hass, api_base_url, api_key, model_name
            )
            if errs:
                errors.update(errs)
            else:
                return self.async_create_entry(
                    title=title,
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
            data_schema=vol.Schema({
                vol.Required("title", default="LLM Smart Assistant"):
                selector.TextSelector(),
                vol.Required(CONF_API_BASE_URL, default=DEFAULT_API_BASE_URL):
                selector.TextSelector(selector.TextSelectorConfig(type="url")),
                vol.Required(CONF_API_KEY):
                selector.TextSelector(selector.TextSelectorConfig(type="password")),
                vol.Required(CONF_MODEL_NAME, default=DEFAULT_MODEL_NAME):
                selector.TextSelector(),
            }),
            errors=errors,
        )


class LLMSmartAssistantOptionsFlow(config_entries.OptionsFlow):
    """Options flow: single page with all settings."""

    def __init__(self, config_entry):
        self._data = {}

    @staticmethod
    def _automation_options(automations):
        if not automations:
            return []
        return [{"value": a.automation_id, "label": f"{a.entity_id} {a.condition} \u2192 {a.description or a.prompt or a.automation_id[:8]}"} for a in automations]

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Remove empty TTS entity to avoid validation error from EntitySelector
            if not user_input.get(CONF_TTS_ENTITY_ID):
                user_input.pop(CONF_TTS_ENTITY_ID, None)
            # Ensure disabled_automations is a list
            if CONF_DISABLED_AUTOMATIONS not in user_input:
                user_input[CONF_DISABLED_AUTOMATIONS] = []
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)

        cur = self.config_entry.options
        dat = self.config_entry.data

        # Build domain list for whitelist
        domains = set([
            "alarm_control_panel", "automation", "binary_sensor", "button",
            "camera", "climate", "cover", "device_tracker", "fan",
            "humidifier", "input_boolean", "light", "lock", "media_player",
            "remote", "scene", "script", "sensor", "siren", "switch",
            "vacuum", "water_heater", "weather", "valve", "update",
            "lawn_mower", "conversation", "event", "todo", "tts", "sun",
        ])
        for state in self.hass.states.async_all():
            d = state.entity_id.split(".")[0]
            if d not in RESTRICTED_DOMAINS:
                domains.add(d)

        # Get automations for disable list
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        automations = list(coordinator._automations.values()) if coordinator else []

        # Migrate old-format full prompts to new shorter defaults
        _old_prompt = cur.get(CONF_PROMPT_DEFAULT, "")
        _is_old_format = len(_old_prompt) > 200 or "You are a smart home assistant integrated with Home Assistant" in _old_prompt
        _migrated_prompt = DEFAULT_PROMPT_DEFAULT if _is_old_format else (_old_prompt or DEFAULT_PROMPT_DEFAULT)
        _old_auto = cur.get(CONF_PROMPT_AUTOMATION, "")
        _is_old_auto_format = len(_old_auto) > 200 or "You are an automation trigger executor for Home Assistant" in _old_auto
        _migrated_auto = DEFAULT_PROMPT_AUTOMATION if _is_old_auto_format else (_old_auto or DEFAULT_PROMPT_AUTOMATION)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                # ── API Configuration ──
                vol.Required(CONF_API_BASE_URL,
                    default=cur.get(CONF_API_BASE_URL, dat.get(CONF_API_BASE_URL, DEFAULT_API_BASE_URL))):
                selector.TextSelector(selector.TextSelectorConfig(type="url")),
                vol.Required(CONF_API_KEY,
                    default=cur.get(CONF_API_KEY, dat.get(CONF_API_KEY, ""))):
                selector.TextSelector(selector.TextSelectorConfig(type="password")),
                vol.Required(CONF_MODEL_NAME,
                    default=cur.get(CONF_MODEL_NAME, dat.get(CONF_MODEL_NAME, DEFAULT_MODEL_NAME))):
                selector.TextSelector(),

                # ── LLM Parameters ──
                vol.Optional(CONF_TEMPERATURE,
                    default=float(cur.get(CONF_TEMPERATURE, dat.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)))):
                selector.NumberSelector(selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.1, mode=selector.NumberSelectorMode.BOX)),
                vol.Optional(CONF_MAX_TOKENS,
                    default=int(cur.get(CONF_MAX_TOKENS, dat.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)))):
                selector.NumberSelector(selector.NumberSelectorConfig(min=64, max=32768, step=1, mode=selector.NumberSelectorMode.BOX)),

                # ── System Prompts ──
                # (migration of old full prompts happens before the schema)
                vol.Optional(CONF_PROMPT_DEFAULT,
                    default=_migrated_prompt):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                vol.Optional(CONF_PROMPT_AUTOMATION,
                    default=_migrated_auto):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True)),

                # ── Input Sensors ──
                vol.Optional(CONF_INPUT_ENTITIES,
                    default=cur.get(CONF_INPUT_ENTITIES, [])):
                selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_text"], multiple=True)),
                vol.Optional(CONF_IGNORE_DUPLICATE,
                    default=cur.get(CONF_IGNORE_DUPLICATE, DEFAULT_IGNORE_DUPLICATE)):
                selector.BooleanSelector(),

                # ── Text-to-Speech ──
                # EntitySelector for UI picker; custom subclass accepts empty string
                vol.Optional(CONF_TTS_ENTITY_ID,
                    default=cur.get(CONF_TTS_ENTITY_ID) or ""):
                _OptionalEntitySelector(selector.EntitySelectorConfig(multiple=False)),
                vol.Optional(CONF_TTS_MODE,
                    default=cur.get(CONF_TTS_MODE, TTS_MODE_STANDARD)):
                selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[TTS_MODE_STANDARD, TTS_MODE_XIAOMI_MIOT, TTS_MODE_CUSTOM],
                )),
                vol.Optional(CONF_TTS_CUSTOM_TEMPLATE,
                    default=cur.get(CONF_TTS_CUSTOM_TEMPLATE, "")):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                # ── TTS Volume & Anti-抢答 ──
                vol.Optional(CONF_TTS_SPEAK_VOLUME,
                    default=float(cur.get(CONF_TTS_SPEAK_VOLUME, DEFAULT_TTS_SPEAK_VOLUME))):
                selector.NumberSelector(selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.1, mode=selector.NumberSelectorMode.BOX)),
                vol.Optional(CONF_TTS_MUTE_AFTER,
                    default=bool(cur.get(CONF_TTS_MUTE_AFTER, DEFAULT_TTS_MUTE_AFTER))):
                selector.BooleanSelector(),
                vol.Optional(CONF_TTS_MUTE_ENTITY_ID,
                    default=cur.get(CONF_TTS_MUTE_ENTITY_ID) or ""):
                _OptionalEntitySelector(selector.EntitySelectorConfig(multiple=False)),

                # ── Security & Access ──
                vol.Optional(CONF_ACCESS_TOKEN,
                    default=cur.get(CONF_ACCESS_TOKEN, dat.get(CONF_ACCESS_TOKEN, ""))):
                selector.TextSelector(selector.TextSelectorConfig(type="password")),
                vol.Optional(CONF_DOMAINS_WHITELIST,
                    default=cur.get(CONF_DOMAINS_WHITELIST, ["light", "switch", "media_player", "input_boolean"])):
                selector.SelectSelector(selector.SelectSelectorConfig(
                    options=sorted(domains), multiple=True, mode=selector.SelectSelectorMode.DROPDOWN,
                )),
                vol.Optional(CONF_ENTITIES_WHITELIST,
                    default=cur.get(CONF_ENTITIES_WHITELIST, [])):
                selector.EntitySelector(selector.EntitySelectorConfig(multiple=True)),
                vol.Optional(CONF_ALLOW_AUTOMATION,
                    default=cur.get(CONF_ALLOW_AUTOMATION, DEFAULT_ALLOW_AUTOMATION)):
                selector.BooleanSelector(),

                # ── Conversation History ──
                vol.Optional(CONF_HISTORY_ENABLED,
                    default=cur.get(CONF_HISTORY_ENABLED, DEFAULT_HISTORY_ENABLED)):
                selector.BooleanSelector(),
                vol.Optional(CONF_HISTORY_MODE,
                    default=cur.get(CONF_HISTORY_MODE, DEFAULT_HISTORY_MODE)):
                selector.SelectSelector(selector.SelectSelectorConfig(
                    options=[HISTORY_MODE_COUNT, HISTORY_MODE_TIME],
                )),
                vol.Optional(CONF_HISTORY_COUNT,
                    default=cur.get(CONF_HISTORY_COUNT, DEFAULT_HISTORY_COUNT)):
                selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=100, step=1, mode=selector.NumberSelectorMode.BOX)),
                vol.Optional(CONF_HISTORY_TIME_WINDOW,
                    default=cur.get(CONF_HISTORY_TIME_WINDOW, DEFAULT_HISTORY_TIME_WINDOW)):
                selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=1440, step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="minutes")),

                # ── Dynamic Automations ──
                vol.Optional(CONF_DISABLED_AUTOMATIONS,
                    default=cur.get(CONF_DISABLED_AUTOMATIONS, [])):
                selector.SelectSelector(selector.SelectSelectorConfig(
                    options=self._automation_options(automations),
                    multiple=True, mode=selector.SelectSelectorMode.DROPDOWN,
                )),
            }),
            errors=errors,
        )
