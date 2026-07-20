# LLM Smart Assistant

[![HACS Custom Integration](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

> [中文](../README.md)

A powerful Home Assistant custom integration that bridges OpenAI-compatible LLMs with your smart home, enabling natural language control, dynamic automations, TTS voice output, and a built-in AI Chat UI.

---

## 📖 Features

| Feature                        | Description                                                   |
| ------------------------------ | ------------------------------------------------------------- |
| 🤖 **Multi-Model LLM Support** | OpenAI, DeepSeek, Kimi, Gemini, and any OpenAI-compatible API |
| 💬 **Built-in AI Chat Panel**  | Full-featured chat interface with multi-round reasoning       |
| 🎤 **Voice Input**             | SpeechRecognition + text sensor monitoring                    |
| 🗣️ **TTS Output**              | Standard TTS, Xiaomi MIoT, and custom templates               |
| ⚡ **Dynamic Automations**     | Create/Edit/Disable automations via natural language          |
| 🔄 **Multi-Step Reasoning**    | LLM checks states, acts, observes, and iterates               |
| 🔒 **Security**                | Domain + entity whitelist, restricted operations              |
| 📝 **Conversation History**    | Count + time-window dual truncation                           |
| 🌐 **Multi-Language**          | English & Chinese UI, expandable                              |
| 🏗️ **Multi-Instance**          | Multiple independent LLM instances                            |

---

## 📦 Installation

### HACS (Recommended)

1. Add this repository as a custom integration repository in HACS (HACS → Integrations → Custom repositories).
2. Search for "LLM Smart Assistant" and install.
3. Restart Home Assistant.

### Manual

Copy the `custom_components/llm_smart_assistant/` directory to your HA `config/custom_components/` directory, then restart HA.

---

## 🚀 Quick Start

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for "LLM Smart Assistant".
3. Enter your LLM API details:
   - **API Base URL**: `https://api.deepseek.com/v1` (or your provider's endpoint)
   - **API Key**: Your API key
   - **Model**: `deepseek-chat`, `gpt-4o-mini`, etc.
4. Open the AI Chat panel from the sidebar, or navigate to `http://<your-ha>:8123/llm-chat`.
5. Start controlling your smart home with natural language.

---

## ⚙️ Configuration

All settings are configured in a single-page form accessible via **Settings → Devices & Services → LLM Smart Assistant → Configure**.

### API Settings

| Field        | Description                                       |
| ------------ | ------------------------------------------------- |
| API Base URL | Your LLM provider's API endpoint                  |
| API Key      | Authentication key                                |
| Model        | Model name (e.g., `gpt-4o-mini`, `deepseek-chat`) |
| Temperature  | Response creativity (0.0–2.0)                     |
| Max Tokens   | Maximum response length                           |

### Prompts

- **Hardcoded Core** — Critical logic (JSON format, actions, loop behavior) is built-in and NOT user-modifiable.
- **Additional Instructions** — User-customizable tips appended after the hardcoded core.
  Supports `{{ time }}`, `{{ date }}`, `{{ exposed_entities }}`.

### Security

- **Allowed Domains** — Which entity domains the LLM can control (default: `light`, `switch`, `media_player`, `sensor`, `input_boolean`).
- **Allowed Entities** — Specific entity whitelist (leave empty to allow all within allowed domains).
- **Allow Automations** — Enable/disable LLM-based automation creation.

### TTS (Text-to-Speech)

| Field           | Description                                                     |
| --------------- | --------------------------------------------------------------- |
| TTS Entity      | Media player to speak through (EntitySelector)                  |
| TTS Mode        | `Standard` (media_player), `Xiaomi MIoT`, or `Custom Template`  |
| Custom Template | Jinja2 template for custom TTS service calls                    |
| Speak Volume    | Volume level (0.0–1.0) to set before speaking                   |
| Mute After      | Enable mute/DND after TTS to prevent speaker echo               |
| Mute Entity     | Separate media_player entity for volume/mute control (optional) |

### Voice Input

Add `sensor.*` entities to **Input Sensors** to enable voice-initiated conversations.
The coordinator monitors state changes and automatically processes new input.

### History

Both constraints apply simultaneously:

- **Max Turns** — Keep last N conversation turns.
- **Time Window** — Keep messages within N minutes.

---

## 💬 AI Chat Panel

The built-in web UI provides:

- **Multi-round Reasoning** — Status shows "Reasoning (round N)..." during processing.
- **Progressive Display** — Responses appear round-by-round.
- **Debug Modal** — Click 🔧 to view the full reasoning trace and the generated prompt (scrollable).
- **Instance Selector** — Switch between multiple configured instances.
- **Automations Tab** — View, create, edit, enable/disable, and delete automations.
- **Voice Input** — Click 🎤 to use browser speech recognition.
- **Mobile Friendly** — Responsive layout.

---

## 🔧 Service Calls

| Service             | Description                                       |
| ------------------- | ------------------------------------------------- |
| `process_input`     | Send text to the LLM for processing               |
| `create_automation` | Create a dynamic automation                       |
| `update_automation` | Edit an automation's entity, condition, or action |
| `toggle_automation` | Enable or disable an automation                   |
| `remove_automation` | Delete an automation                              |
| `get_automations`   | List all automations                              |

---

## ⚡ Dynamic Automations

Create automations using natural language:

> "Turn on the AC when the temperature exceeds 30°C"
> → Creates: `sensor.living_room_temperature > 30` → turn on air conditioner

Automations are persisted across restarts and use Home Assistant's event system for real-time state change detection.

---

## 📁 File Structure

```
custom_components/llm_smart_assistant/
├── __init__.py
├── manifest.json
├── const.py
├── config_flow.py
├── coordinator.py
├── services.py
├── sensor.py
├── services.yaml
├── icons.json
├── brand/
│   ├── icon.png
│   └── logo.png
├── panel/
│   ├── index.html        # AI Chat UI
│   └── chat.js           # Sidebar panel component
└── translations/
    ├── en.json
    └── zh-Hans.json
```

---

## 📋 Requirements

- Home Assistant 2024.6+
- Python 3.12+
- An OpenAI-compatible LLM API key

---

## 📄 License

MIT
