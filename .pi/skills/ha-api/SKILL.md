---
name: ha-api
description: |
  Home Assistant REST API interactions. Use for calling services, querying
  states, getting auth tokens, managing config entries, reading logs,
  and all HA-integrated test operations in this project.
  Token and endpoint are project-specific (localhost:8123).
---

# Home Assistant REST API

## Authentication

Use a **long-lived access token** (HA → Profile → Security → Long-lived access tokens).
Local credentials live in the gitignored `.user/` directory at the project root:

```bash
# One-time: save your long-lived token (or let dev-setup create it)
mkdir -p .user && echo "YOUR_LONG_LIVED_TOKEN" > .user/hass_token && chmod 600 .user/hass_token

# Every session: load it (from the project root)
TOKEN=$(cat .user/hass_token)

# Verify it works
curl -s http://localhost:8123/api/ -H "Authorization: Bearer $TOKEN"
# → {"message": "API running."}
```

`.user/credentials.json` additionally stores the HA login and LLM API
credentials, and is read/written by `dev-setup/setup_env.py`.

Alternative: exchange a refresh token for a short-lived access token via
`POST /auth/token` (grant_type=refresh_token) — only needed when no long-lived
token exists.

## State & Entity Queries

```bash
# List a specific entity state
curl -s "http://localhost:8123/api/states/sensor.llm_last_response" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# List all entities
curl -s "http://localhost:8123/api/states" -H "Authorization: Bearer $TOKEN"

# Filter by domain
curl -s "http://localhost:8123/api/states" -H "Authorization: Bearer $TOKEN" | \
  python3 -c "import sys,json;[print(s['entity_id'],s['state']) for s in json.load(sys.stdin) if s['entity_id'].startswith('input_boolean')]"
```

## Service Calls

```bash
# Call a service
curl -s -X POST "http://localhost:8123/api/services/DOMAIN/SERVICE" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "ENTITY_ID"}'

# Common examples:
# input_boolean.turn_on / turn_off
# input_number.set_value (with "value": 31)
# homeassistant.set_state (with "state": "new_value")

# Call service with response (for services that return data)
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/get_automations?return_response=1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
# Response format: {"changed_states":[],"service_response":{...}}
```

## LLM Smart Assistant Specific

```bash
# Process a user input (main entry point)
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/process_input" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Turn on the living room light"}'

# Create automation directly
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/create_automation" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "sensor.living_room_temperature", "condition": ">30", "prompt": "Turn on the AC", "description": "Auto AC"}'

# Remove automation
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/remove_automation" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"automation_id": "ID"}'

# List automations (need ?return_response=1)
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/get_automations?return_response=1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Config & Options Flow

```bash
# Start options flow
RAW=$(curl -s -X POST "http://localhost:8123/api/config/config_entries/options/flow" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"handler": "ENTRY_ID"}')
FLOW_ID=$(echo "$RAW" | python3 -c "import sys,json;print(json.load(sys.stdin)['flow_id'])")

# Submit a step
curl -s -X POST "http://localhost:8123/api/config/config_entries/options/flow/$FLOW_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"field1": "value1", "field2": "value2"}'
# Final step returns: {"type": "create_entry", ...}

# List config entries
curl -s "http://localhost:8123/api/config/config_entries/entry" \
  -H "Authorization: Bearer $TOKEN"

# Filter by domain
curl -s "http://localhost:8123/api/config/config_entries/entry/llm_smart_assistant" \
  -H "Authorization: Bearer $TOKEN"
```

## HA Logs

Paths below are relative to the project root (where `docker-compose.yml` lives).

```bash
# Check logs (from host, not docker)
cat config/home-assistant.log | grep "KEYWORD" | tail -10

# From docker
docker exec hass-dev grep "KEYWORD" /config/home-assistant.log | tail -10

# Common keywords to grep:
# "Reasoning" - LLM reasoning rounds
# "Round" - individual round output
# "LLM JSON parsed" - parsed LLM response
# "completed" - reasoning completion
# "automation" - automation events
# "triggered" - automation triggers
# "Error" - errors
# "Step execution" - service call execution
```

## Testing Pattern

```bash
# Full test: send command → wait → check sensor → check entity

# 1. Reset entity
curl -s -X POST "http://localhost:8123/api/services/input_boolean/turn_off" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "input_boolean.living_room_light"}'

# 2. Send command
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/process_input" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Turn on the living room light"}'

# 3. Wait for processing (API takes 3-10 seconds per round)
sleep 12

# 4. Check sensor
curl -s "http://localhost:8123/api/states/sensor.llm_last_response" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
r = json.loads(d['attributes'].get('full_response','{}'))
print(f'TTS: {d.get(\"state\",\"\")[:80]}')
print(f'iterations: {r.get(\"iterations\")}')
print(f'in_progress: {d[\"attributes\"].get(\"in_progress\")}')
"

# 5. Verify side effect
curl -s "http://localhost:8123/api/states/input_boolean.living_room_light" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin).get('state'))"
```

## Triggering Automations

```bash
# Set temperature to trigger >30 automation
curl -s -X POST "http://localhost:8123/api/services/input_number/set_value" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "input_number.test_temperature", "value": 35}'
```

## Virtual Devices (test entities)

```yaml
input_boolean.living_room_light  # "客厅灯"
input_boolean.bed_room_light     # "卧室灯"  
input_boolean.tv                 # "TV"
input_boolean.air_conditioner    # "空调"
sensor.living_room_temperature   # Template: reads input_number.test_temperature
input_number.test_temperature    # Adjustable, -10..50°C
```
