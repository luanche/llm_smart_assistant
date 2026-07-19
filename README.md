# LLM Smart Assistant / LLM 智能助手

[![HACS Custom Integration](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A powerful Home Assistant custom integration that bridges OpenAI-compatible LLMs with your smart home, enabling natural language control, dynamic automations, TTS voice output, and a built-in chat UI.

---

## Features

- **🤖 Multi-Model LLM Support** — OpenAI, DeepSeek, Kimi, Gemini, and any OpenAI-compatible API.
- **💬 Built-in AI Chat Panel** — Full-featured chat UI with multi-round reasoning, progress display, and debug modal.
- **🎤 Voice Input** — SpeechRecognition (browser) + text sensor monitoring.
- **🗣️ TTS Output** — Standard TTS, Xiaomi MIoT, and custom Jinja2 templates.
- **⚡ Dynamic Automations** — Create/Edit/Disable automations via natural language, persisted across restarts.
- **🔄 Multi-Step Reasoning (ReAct)** — LLM checks states, acts, observes, and iterates until complete.
- **🔒 Security** — Domain + entity whitelist, restricted operations, action interceptor.
- **📝 Conversation History** — Smart history with count + time-window dual truncation.
- **🌐 Multi-Language** — English + Chinese UI, easy to extend (see `LANGUAGES` in `index.html`).
- **⚙️ Full Config Flow** — 24 fields in a single-page comprehensive form.
- **🏗️ Multi-Instance** — Multiple independent LLM instances with per-instance chat selection.

---

## Installation

### HACS (Recommended)

1. Add this repo as a custom integration repository in HACS.
2. Search for "LLM Smart Assistant" and install.
3. Restart Home Assistant.

### Manual

```bash
cp -r custom_components/llm_smart_assistant /path/to/ha/config/custom_components/
# Restart HA
```

### Docker Development

```bash
git clone <repo-url>
cd llm_smart_assistant
docker compose up -d
# Access at http://localhost:8123
```

---

## Quick Start

1. **Add Integration**: Settings → Devices & Services → Add Integration → "LLM Smart Assistant"
2. **Configure API**: Enter Base URL (e.g. `https://api.deepseek.com/v1`), API Key, Model
3. **Open AI Chat**: Navigate to `http://<ha-url>/llm-chat` or click "AI Chat" in the sidebar
4. **Start Talking**: Type "turn on the living room light" or "创建自动化，当温度>30度打开空调"

---

## Configuration

### Initial Setup

| Field | Description | Example |
|-------|-------------|---------|
| API Base URL | OpenAI-compatible endpoint | `https://api.deepseek.com/v1` |
| API Key | Your API key | `sk-...` |
| Model Name | Model identifier | `deepseek-chat`, `gpt-4o-mini` |
| Temperature | Creativity (0.0–2.0) | `0.4` |
| Max Tokens | Max response length | `1024` |
| Title | Instance name (for multi-instance) | `Living Room AI` |

### Prompts

- **Default Prompt** — System prompt for general chat (uses `{{ time }}`, `{{ date }}`, `{{ exposed_entities }}`)
- **Automation Prompt** — System prompt for automation trigger execution

### Security

- **Allowed Domains** — Default: `light`, `switch`, `media_player`, `sensor`, `input_boolean`
- **Allowed Entities** — Specific entity whitelist (empty = all in allowed domains)
- **Allow Automations** — Enable/disable natural language automation creation

### History

Both count AND time-window constraints apply simultaneously:
- **Max Turns** — Keep last N conversation turns
- **Time Window** — Keep messages within N minutes

---

## AI Chat Panel

The built-in web UI at `/llm-chat` provides:

- **Multi-Round Reasoning** — Shows "Reasoning (round N)..." during processing
- **Progressive Display** — Responses appear round-by-round
- **Debug Modal** — Small 📋 button shows full reasoning trace per round
- **Instance Selector** — Switch between multiple LLM instances
- **Automations Management** — View, enable/disable, edit, delete, and add automations
- **Voice Input** — Browser SpeechRecognition (🎤 button)
- **Mobile Responsive** — Adapts to small screens

The panel uses a `data-i18n` attribute system for multi-language support. Adding a new language is as simple as adding an entry to the `LANGUAGES` object in `index.html`.

---

## Service Calls

| Service | Parameters | Description |
|---------|-----------|-------------|
| `process_input` | `text`, `entry_id` (optional) | Send text for LLM processing |
| `create_automation` | `entity_id`, `condition`, `prompt`, `description` | Create a dynamic automation |
| `update_automation` | `automation_id`, `entity_id`, `condition`, `prompt` | Update automation fields + re-register listener |
| `toggle_automation` | `automation_id`, `disable`, `entry_id` | Enable/disable automation (adds/removes listener) |
| `remove_automation` | `automation_id` | Delete an automation |
| `get_automations` | — | List all automations with disabled status |

---

## Dynamic Automations

Created via natural language or the "Add Automation" button in the AI Chat panel.

```
User: "当温度高于30度时打开空调"
→ LLM creates: sensor.living_room_temperature >30 → turn on input_boolean.air_conditioner
```

Automations are:
- **Persisted** across HA restarts (stored in `.storage/llm_smart_assistant.storage`)
- **Listener-based** — Uses `async_track_state_change_event` for real-time triggers
- **Editable** — Entity, condition, and action can be changed via the Edit modal
- **Disableable** — Disabling removes the listener entirely; re-enabling re-registers it

---

## File Structure

```
custom_components/llm_smart_assistant/
├── __init__.py           # Entry point, services, panel registration
├── manifest.json         # Dependencies and version
├── const.py              # Constants, defaults, prompts
├── config_flow.py        # Single-page config/options flow (24 fields)
├── coordinator.py        # Core: LLM API, reasoning loop, automation listeners
├── services.py           # Action executor with whitelist interceptor
├── sensor.py             # LLMLastResponseSensor + LLMDebugRawSensor
├── services.yaml         # Service definitions
├── icon.svg              # Integration icon
├── panel/
│   ├── index.html        # AI Chat UI (multi-language via data-i18n)
│   └── chat.js           # LitElement wrapper for sidebar panel
└── translations/
    ├── en.json           # HA translation keys (English)
    └── zh-Hans.json      # HA translation keys (Chinese)
```

---

## Development

```bash
# Start environment
docker compose up -d

# Check logs
docker compose logs -f

# The integration code is at custom_components/llm_smart_assistant/
# Panel files are read fresh on each request (no restart needed for HTML/JS changes)

# Run i18n audit
python3 .pi/skills/i18n-audit/check.py

# Save i18n baseline for diff
python3 .pi/skills/i18n-audit/check.py --save-baseline
```

### Requirements

- Home Assistant 2024.6+
- Python 3.12+
- OpenAI-compatible API key

---

## Security

- **Read-Only Default** — LLM cannot modify system configuration
- **Domain Whitelist** — Only allowed domains can be controlled
- **Entity Whitelist** — Specific entity-level restrictions
- **Restricted Operations** — Core HA operations (restart, stop, config changes) always blocked
- **Action Interceptor** — Every LLM-requested action validated before execution

---

## License

MIT
