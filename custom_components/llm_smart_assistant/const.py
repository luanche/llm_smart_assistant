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
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_PROMPT_DEFAULT: Final = "prompt_default"
CONF_PROMPT_AUTOMATION: Final = "prompt_automation"
CONF_INPUT_ENTITIES: Final = "input_entities"
CONF_TTS_ENTITY_ID: Final = "tts_entity_id"
CONF_TTS_MODE: Final = "tts_mode"
CONF_TTS_CUSTOM_TEMPLATE: Final = "tts_custom_template"
CONF_TTS_SPEAK_VOLUME: Final = "tts_speak_volume"
CONF_TTS_MUTE_AFTER: Final = "tts_mute_after"
CONF_TTS_MUTE_ENTITY_ID: Final = "tts_mute_entity_id"
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
DEFAULT_MAX_TOKENS: Final = 4096
DEFAULT_HISTORY_ENABLED: Final = True
DEFAULT_HISTORY_MODE: Final = "count"
DEFAULT_HISTORY_COUNT: Final = 10
DEFAULT_HISTORY_TIME_WINDOW: Final = 60  # 1 hour
DEFAULT_IGNORE_DUPLICATE: Final = True
DEFAULT_ALLOW_AUTOMATION: Final = True
DEFAULT_TTS_SPEAK_VOLUME: Final = 0.5
DEFAULT_TTS_MUTE_AFTER: Final = True

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
ACTION_INSPECT: Final = "inspect"

# Multi-step reasoning limits
MAX_REASONING_ITERATIONS: Final = 10
REASONING_TIMEOUT: Final = 120  # seconds total for all rounds

# Internal events/keys
STORAGE_KEY: Final = f"{DOMAIN}.storage"
STORAGE_VERSION: Final = 1

# ── Hardcoded system prompt core (NOT user-modifiable) ──────────────────────
# This part is ALWAYS prepended to the user's custom prompt. It defines the
# required JSON output format, available actions, and reasoning loop behavior
# that the integration depends on for correct operation.
HARDCODED_SYSTEM_PROMPT: Final = """You control Home Assistant devices. Convert user requests into JSON actions.

## Entities (use ONLY these entity_ids)
{{ exposed_entities }}

Time: {{ time }} {{ date }}  Max rounds: {{ max_iterations }}

## Output format: raw JSON, no markdown
{"tts_text": "reply to user", "steps": [{"action": "...", ...}]}
Set tts_text to "" when steps NOT empty.

## Available actions
1. get_states: Check states + available services
   {"action": "get_states", "entities": ["id1", "id2"]}
2. call_service: Call any service on any entity
   {"action": "call_service", "domain": "input_boolean", "service": "turn_on",
    "target": {"entity_id": "input_boolean.living_room_light"}}
   Common services: turn_on, turn_off, toggle (most domains)
   Domain-specific: set_temperature (climate), press (button), etc.
3. create_automation: Create a trigger-based rule
   {"action": "create_automation", "entity_id": "sensor.temp",
    "condition": ">30", "prompt": "turn on AC"}
4. tts_speak: Speak mid-execution
   {"action": "tts_speak", "text": "message"}

## Rules
1. Check states first (get_states), then act (call_service), then finish (steps: []).
2. tts_text="" when steps has actions. Only speak when done.
3. Final reply: one short sentence when steps: []. No repeats.
4. Use ONLY entity_ids from the list. Never invent entities.
5. Already in target state? Skip action, finish.
6. Service failed? Skip, explain in final tts_text.
7. Need user input? Ask via tts_text, set steps: [], wait for reply.
"""

# Hardcoded automation trigger prompt core (NOT user-modifiable)
HARDCODED_AUTOMATION_PROMPT: Final = """You are an automation trigger handler. Execute the task described below.

## Available Entities (use ONLY these)
{{ exposed_entities }}

## Output: raw JSON
{"tts_text": "", "steps": [...]}

## Allowed Actions
1. call_service — Execute a service on device(s)
   {"action": "call_service", "domain": "switch", "service": "turn_on",
    "target": {"entity_id": "switch.living_room"}}
2. get_states / inspect — Check entity states
   {"action": "get_states", "entities": ["entity_id"]}

## Rules
1. Use ONLY entity_ids from the list above. Never invent entities.
2. Set tts_text="" unless a spoken response is truly needed.
3. On success, return steps with the executed action, then steps: [].
4. If task is impossible (missing entity/config), return steps: [] and explain in tts_text."""

# ── User-customizable prompt parts ─────────────────────────────────────────
# These are appended after the hardcoded core. Users can override them in config.
DEFAULT_PROMPT_DEFAULT: Final = """Reply in the SAME language as the user.
"""
DEFAULT_PROMPT_AUTOMATION: Final = """Reply in the SAME language as the user task.
"""

# Restricted domains that the LLM is NEVER allowed to control
RESTRICTED_DOMAINS: Final = [
    "homeassistant",
    "person",
    "auth",
    "config",
    "input_button",
    "input_datetime",
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
