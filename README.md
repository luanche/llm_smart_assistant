# LLM Smart Assistant / LLM 智能助手

[![HACS Custom Integration](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A powerful Home Assistant custom integration that bridges OpenAI-compatible LLMs (Large Language Models) with your smart home, enabling natural language control, dynamic automations, and TTS voice output.

一款强大的 Home Assistant 自定义集成，桥接兼容 OpenAI API 的大语言模型与您的智能家居，实现自然语言控制、动态自动化和 TTS 语音播报。

---

## Features / 功能特性

- **🤖 Multi-Model LLM Support / 多模型 LLM 支持**: Compatible with OpenAI, DeepSeek, Kimi, Gemini, and any OpenAI-compatible API provider.
- **🎤 Voice Input via Sensors / 传感器语音输入**: Listen to any text sensor (ESP32, Xiaomi, custom voice assistants).
- **🗣️ TTS Output / 语音播报**: Support standard TTS, Xiaomi MIoT, and custom templates.
- **🔒 Security First / 安全优先**: Strict whitelist mechanism, restricted domain protection, read-only default.
- **⚡ Dynamic Automations / 动态自动化**: Create automations using natural language, persisted across restarts.
- **📝 Conversation History / 对话历史**: Smart history management with count-based or time-window truncation.
- **🌐 Multi-language UI / 多语言界面**: English and Chinese UI supported.
- **⚙️ Full Config Flow / 完整配置界面**: All settings configurable via Home Assistant UI.

---

## Installation / 安装

### HACS Installation (Recommended) / HACS 安装（推荐）

1. Add this repository as a custom repository in HACS:
   - HACS → Integrations → Custom repositories
   - Repository: `https://github.com/your_username/llm_smart_assistant`
   - Category: Integration
2. Search for "LLM Smart Assistant" in HACS and install.
3. Restart Home Assistant.

### Manual Installation / 手动安装

1. Copy the `custom_components/llm_smart_assistant` directory to your HA `config/custom_components/` directory.
2. Restart Home Assistant.

### Docker Local Development / Docker 本地开发

```bash
# Clone the repository
git clone https://github.com/your_username/llm_smart_assistant.git
cd llm_smart_assistant

# Start Home Assistant with the integration
docker compose up -d

# Access at http://localhost:8123
```

---

## Configuration / 配置

### Initial Setup / 初始设置

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for "LLM Smart Assistant".
3. Enter your API configuration:
   - **API Base URL**: e.g., `https://api.openai.com/v1`
   - **API Key**: Your API key
   - **Model Name**: e.g., `gpt-4o-mini`, `deepseek-chat`
   - **Temperature**: Response creativity (0.0 - 2.0)
   - **Max Tokens**: Maximum response length

### Options Configuration / 选项配置

After installation, click **Configure** on the integration to set up:

#### Prompts / 提示词
- **Default Prompt**: System prompt for general conversations.
- **Automation Prompt**: System prompt for automation triggers.

Available context variables:
- `{{ time }}` - Current time
- `{{ date }}` - Current date
- `{{ exposed_entities }}` - List of accessible entities

#### Input Sensors / 输入传感器
- Select text sensor entities to monitor.
- Enable/disable duplicate input filtering.

#### TTS Configuration / TTS 配置
- **Target Entity**: Media player or TTS entity.
- **Mode**: Standard, Xiaomi MIoT, or Custom template.
- **Custom Template**: Jinja2 template for custom TTS actions.

#### Security / 安全
- **Allowed Domains**: e.g., `light`, `switch`, `media_player`
- **Allowed Entities**: Specific entities the LLM can control.
- **Allow Dynamic Automations**: Enable/disable natural language automation creation.

#### History / 历史记录
- **Mode**: Count-based or time-window based truncation.
- **Count/Max Turns**: Number of conversation turns to keep.
- **Time Window**: Time window in minutes.

---

## Usage / 使用

### Voice Control / 语音控制

When a monitored text sensor changes state (e.g., a voice assistant captures speech), the integration automatically:

1. Receives the text input
2. Builds context with HA state information
3. Sends to LLM with the configured system prompt
4. Parses the JSON response
5. Executes actions (turn on lights, adjust climate, etc.)
6. Speaks the response via TTS

### Service Calls / 服务调用

The integration exposes these services:

| Service | Description |
|---------|-------------|
| `llm_smart_assistant.process_input` | Manually send text for processing |
| `llm_smart_assistant.create_automation` | Create a dynamic automation |
| `llm_smart_assistant.remove_automation` | Remove a dynamic automation |
| `llm_smart_assistant.get_automations` | List all active automations |

### Example LLM Response Format / 示例 LLM 响应格式

The LLM must respond in this JSON format:

```json
{
  "tts_text": "好的，已经为您打开了客厅的灯。",
  "steps": [
    {
      "action": "call_service",
      "domain": "light",
      "service": "turn_on",
      "target": { "entity_id": "light.living_room" }
    }
  ]
}
```

### Dynamic Automation Example / 动态自动化示例

User says: "帮我创建一个自动化，当温度高于30度时帮我开空调"

The LLM responds with:
```json
{
  "tts_text": "已为您创建温度自动化",
  "steps": [
    {
      "action": "create_automation",
      "entity_id": "sensor.temperature",
      "condition": ">30",
      "description": "当温度高于30度时开空调"
    }
  ]
}
```

---

## File Structure / 文件结构

```
custom_components/llm_smart_assistant/
├── __init__.py           # Integration entry point
├── manifest.json         # Dependency declaration and version
├── const.py              # Constants and default values
├── config_flow.py        # ConfigFlow and OptionsFlow
├── coordinator.py        # Core logic: state listening, LLM API, response parsing
├── services.py           # Action executor with whitelist interceptor
├── storage.py            # Dynamic automation persistence
├── services.yaml         # Service definitions
├── translations/
│   ├── en.json           # English translations
│   └── zh-Hans.json      # Chinese translations
```

---

## Security / 安全机制

- **Read-Only Default**: LLM cannot modify system configuration by default.
- **Domain Whitelist**: Only allowed domains can be controlled.
- **Entity Whitelist**: Specific entity-level control.
- **Restricted Operations**: Core HA operations (restart, stop, config changes) are always blocked.
- **Action Interceptor**: Every LLM-requested action is validated before execution.

---

## Requirements / 系统要求

- Home Assistant 2024.6 or later
- An OpenAI-compatible API key (or any compatible provider)
- Python 3.12+

---

## Development / 开发

```bash
# Clone the repository
git clone https://github.com/your_username/llm_smart_assistant.git
cd llm_smart_assistant

# Start dev environment
docker compose up -d

# Check logs
docker compose logs -f homeassistant

# The integration code is in custom_components/llm_smart_assistant/
# Changes are automatically reflected in the running container
```

---

## License / 许可证

MIT License

Copyright (c) 2024

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
