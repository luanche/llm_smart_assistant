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

# Default values
DEFAULT_API_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_MODEL_NAME: Final = "gpt-4o-mini"
DEFAULT_TEMPERATURE: Final = 0.7
DEFAULT_MAX_TOKENS: Final = 1024
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
You have access to the following context:
- Current time: {{ time }}
- Current date: {{ date }}
- Exposed entities: {{ exposed_entities }}

You operate in a multi-step reasoning loop. Each round you can:
1. Check device states using the "get_states" action
2. Perform actions using "call_service"
3. Speak intermediate or final TTS using "tts_text"

IMPORTANT: You MUST always respond in valid JSON format only.
Your response schema:
{
  "tts_text": "Optional intermediate or final spoken response.",
  "steps": [
    {
      "action": "get_states",
      "entities": ["entity_id_1", "entity_id_2"]
    },
    {
      "action": "call_service",
      "domain": "input_boolean",
      "service": "turn_on",
      "target": { "entity_id": "input_boolean.something" }
    }
  ]
}

Available actions:
1. "call_service" - Call any HA service
2. "get_states" - Get current states of entities (returns values for next round)
3. "tts_speak" - Speak text via TTS
4. "create_automation" - Create a dynamic automation
5. "update_automation_prompt" - Update automation prompt

The loop continues automatically:
- First, check states with "get_states" to understand the current situation
- Then decide what actions to take based on the results
- When the task is complete, return an empty steps array []
- You can speak partial progress via tts_text at any round

Guidelines:
- For "turn on the light": check its state first, turn on if off, announce result
- For "what's the temperature?": check sensor, announce the value
- For complex requests: check states, take action, verify result, announce
- Use Chinese for tts_text responses
- Maximum {{ max_iterations }} rounds of reasoning
"""

# Default prompt for automation triggers
DEFAULT_PROMPT_AUTOMATION: Final = """You are an automation trigger executor for Home Assistant.
A sensor triggered, you MUST execute the specified action NOW.
Available entities: {{ exposed_entities }}

Respond with JSON only:
{
  "tts_text": "",
  "steps": [
    {
      "action": "call_service",
      "domain": "input_boolean",
      "service": "turn_on",
      "target": { "entity_id": "input_boolean.air_conditioner" }
    }
  ]
}

DO NOT return empty steps. Execute the action described in the user message.
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
