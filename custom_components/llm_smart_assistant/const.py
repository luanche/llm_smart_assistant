"""Constants for the LLM Smart Assistant integration."""

import logging
from typing import Final

DOMAIN: Final = "llm_smart_assistant"

_LOGGER = logging.getLogger(__name__)

# Configuration keys
CONF_API_BASE_URL: Final = "api_base_url"
CONF_API_KEY: Final = "api_key"
CONF_MODEL_NAME: Final = "model_name"
CONF_TEMPERATURE: Final = "temperature"
CONF_MAX_TOKENS: Final = "max_tokens"
CONF_PROMPT_DEFAULT: Final = "prompt_default"
CONF_PROMPT_AUTOMATION: Final = "prompt_automation"
CONF_INPUT_ENTITIES: Final = "input_entities"
CONF_TTS_ENTITY_ID: Final = "tts_entity_id"
CONF_TTS_MODE: Final = "tts_mode"
CONF_TTS_CUSTOM_TEMPLATE: Final = "tts_custom_template"
CONF_DOMAINS_WHITELIST: Final = "domains_whitelist"
CONF_ENTITIES_WHITELIST: Final = "entities_whitelist"
CONF_HISTORY_MODE: Final = "history_mode"  # "count" or "time"
CONF_HISTORY_COUNT: Final = "history_count"
CONF_HISTORY_TIME_WINDOW: Final = "history_time_window"  # in minutes
CONF_IGNORE_DUPLICATE: Final = "ignore_duplicate"
CONF_ALLOW_AUTOMATION: Final = "allow_automation"
CONF_HISTORY_ENABLED: Final = "history_enabled"
CONF_DISABLED_AUTOMATIONS: Final = "disabled_automations"

# Default values
DEFAULT_API_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_MODEL_NAME: Final = "gpt-4o-mini"
DEFAULT_TEMPERATURE: Final = 0.7
DEFAULT_MAX_TOKENS: Final = 2048
DEFAULT_HISTORY_ENABLED: Final = True
DEFAULT_HISTORY_MODE: Final = "count"
DEFAULT_HISTORY_COUNT: Final = 10
DEFAULT_HISTORY_TIME_WINDOW: Final = 60  # 1 hour
DEFAULT_IGNORE_DUPLICATE: Final = True
DEFAULT_ALLOW_AUTOMATION: Final = True

# TTS modes
TTS_MODE_STANDARD: Final = "standard"
TTS_MODE_XIAOMI_MIOT: Final = "xiaomi_miot"
TTS_MODE_CUSTOM: Final = "custom"

# Action types
ACTION_CALL_SERVICE: Final = "call_service"
ACTION_CREATE_AUTOMATION: Final = "create_automation"
ACTION_UPDATE_AUTOMATION_PROMPT: Final = "update_automation_prompt"
ACTION_TTS_SPEAK: Final = "tts_speak"
ACTION_GET_STATES: Final = "get_states"

# Multi-step reasoning limits
MAX_REASONING_ITERATIONS: Final = 10
REASONING_TIMEOUT: Final = 120  # seconds total for all rounds

# Internal events/keys
STORAGE_KEY: Final = f"{DOMAIN}.storage"
STORAGE_VERSION: Final = 1

# Default system prompts
DEFAULT_PROMPT_DEFAULT: Final = """You are a smart home assistant integrated with Home Assistant.
Devices: {{ exposed_entities }}
Time: {{ time }} {{ date }}

OUTPUT FORMAT (JSON only, no other text):
{"tts_text": "", "steps": []}

RULES:
1. LANGUAGE: Reply in the SAME language as the user.
2. SILENCE: Set tts_text="" until task is fully done. Never speak intermediate progress.
3. CONCISE: One short sentence when done. Never repeat yourself.
4. STEPS: Check state first (get_states), then act (call_service), then stop (empty steps).
5. JSON ONLY: No explanations before or after the JSON.

Actions:
- call_service: {"action":"call_service","domain":"...","service":"...","target":{"entity_id":"..."}}
- get_states: {"action":"get_states","entities":["id1","id2"]}
- create_automation: {"action":"create_automation","entity_id":"...","condition":">30","prompt":"...","description":"..."}

Loop: get_states → call_service → []. Max {{ max_iterations }} rounds.
"""

# Default prompt for automation triggers
DEFAULT_PROMPT_AUTOMATION: Final = """You are an automation trigger executor for Home Assistant.
Execute the action described in the user message NOW.

Respond with JSON:
{
  "tts_text": "",
  "steps": [
    {
      "action": "call_service",
      "domain": "actual_domain",
      "service": "actual_service",
      "target": { "entity_id": "actual_entity_id" }
    }
  ]
}

RULES:
- Respond in the LANGUAGE specified in the "Language:" field of the trigger message.
- If no Language field is present, use the language of the user's task description.
- Use ONLY entity_ids listed in "Available devices" from the user message.
- Do NOT make up entity IDs or domains.
- Return empty steps [] only if execution is impossible.
- Keep tts_text empty unless a spoken response is necessary.
"""

# Restricted domains that the LLM is NEVER allowed to control
RESTRICTED_DOMAINS: Final = [
    "homeassistant",
    "person",
    "auth",
    "config",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "scene",
    "script",
    "automation",
    "group",
    "zone",
]

# Restricted services that are NEVER allowed
RESTRICTED_SERVICES: Final = [
    "homeassistant.restart",
    "homeassistant.stop",
    "homeassistant.check_config",
    "homeassistant.reload_core_config",
    "homeassistant.reload_all",
    "homeassistant.update_entity",
    "persistent_notification.create",
    "persistent_notification.dismiss",
    "logger.set_default_level",
    "logger.set_levels",
    "system_log.clear",
    "system_log.write",
]

# History modes
HISTORY_MODE_COUNT: Final = "count"
HISTORY_MODE_TIME: Final = "time"
