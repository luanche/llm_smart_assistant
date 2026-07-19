# Home Assistant 智能 AI 助手 (HACS 自定义集成) 需求文档

## 1. 项目概述

本项目旨在开发一个 Home Assistant (HA) 的自定义集成（Custom Integration），支持通过 HACS 安装。该集成作为一个中枢型 AI 助手，能够桥接任何兼容 OpenAI API 格式的大语言模型（如 GPT, DeepSeek, Kimi, Gemini 等），通过监听特定的文本传感器（Sensor）获取用户输入，结合 HA 上下文与预设 Prompt 请求 LLM，并解析 LLM 的返回来自动调用 HA 的 API（RESTful / WebSocket 或内部 Service Call）执行控制或查询任务，最后通过 TTS 将对话结果播报给用户。

同时，该集成具备“自然语言创建自动化”的高级功能，允许 AI 动态修改监听条件并触发对应流程。

## 2. 核心功能模块

### 2.1 LLM 接口管理

- **协议兼容**：完全兼容标准 OpenAI API 请求格式（需使用 `aiohttp` 保证纯异步，严禁使用阻塞的 `requests` 库）。
- **自定义配置**：支持在 HA 的 UI 界面配置以下参数：
  - `Base URL` (如 `https://api.deepseek.com/v1`)
  - `API Key`
  - `Model Name` (如 `deepseek-chat`, `gpt-4o-mini`)
  - `Temperature` 和 `Max Tokens`
- **上下文管理**：集成需在内存中维护最近对话历史，提供两种截断策略（在配置中可选）：
  - 按**对话条数**保留（如保留最近 10 条）。
  - 按**时间窗口**保留（如仅保留过去 1 小时内的对话）。

### 2.2 触发与输入源 (Input Listener)

- **Sensor 监听**：集成需要利用 HA 的 `async_track_state_change_event` 监听配置中指定的一个或多个文本 Sensor（例如 `sensor.xiaomi_oh2p_xxx_conversation`, `sensor.voice_input_1`, `sensor.esp_text_command`）。
- **防抖与去重逻辑**：
  - 当 Sensor 的 `state` 发生变化且不为空 (`unavailable`, `unknown`, `""`) 时触发。
  - 需提供配置项：“忽略重复输入”（当新状态与上次状态完全一致时，是否拦截执行）。

### 2.3 提示词管理 (Prompt Management)

支持通过 HA 的配置界面 (Options Flow) 或 YAML 文件维护多种 System Prompt：

- **默认 Prompt (Default Prompt)**：用于日常对话。系统需在请求前自动注入当前 HA 环境的基础信息变量（如 `{{ time }}`, `{{ date }}`, `{{ exposed_entities }}` 等），并明确告知 LLM 必须严格按照指定的 JSON 格式返回。
- **自动化 Prompt (Automation Prompt)**：当触发动态自动化流程时使用的专用 Prompt。

### 2.4 LLM 返回解析与 HA API 交互 (核心动作)

- **响应结构约定**：请求大模型时应开启 `response_format: { "type": "json_object" }`（若模型支持），强制约束 LLM 返回如下结构：
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
- **HA API 执行层**：解析 `steps` 中的指令。为了最高效，建议直接在集成内部通过 `hass.services.async_call` 调用本地服务，或通过 WebSocket/RESTful 规范执行。
- **内置/默认 Step**：除操作设备外，增加特定的内部 Action。例如 `action: update_automation_prompt`。

### 2.5 语音播报输出 (TTS Action)

- **输出通道映射**：允许用户绑定目标音箱设备的 Entity ID。
- **多模式支持**：
  - **标准模式**：调用 HA 标准的 `tts.speak` 或 `media_player.play_media`。
  - **特定生态支持**：支持选择 `xiaomi_miot` 生态，调用 `xiaomi_miot.play_text` 或 `xiaomi_miot.intelligent_speaker`。
  - **自定义 YAML 模板**：允许高级玩家通过 Jinja2 模板自定义 Action。例如：接收 `tts_text` 变量并映射到自定义的 MQTT 发布服务。

### 2.6 自然语言生成自动化 (Dynamic Automations)

- **逻辑流**：
  1.  用户语音：“帮我创建一个自动化，当温度高于30度时帮我开空调”。
  2.  LLM 返回特殊的 step：`{"action": "create_automation", "entity_id": "sensor.temperature", "condition": ">30", "prompt": "..."}`。
  3.  本集成在 HA 内部注册一个新的状态监听器 (`async_track_state_change`)。
  4.  当满足条件时，静默调用 LLM 获取执行步骤，系统执行并可选是否 TTS 播报。
- **持久化要求 (关键)**：通过 HA 的 `homeassistant.helpers.storage` API 将这些动态创建的自动化保存到 `.storage/` 目录下。确保 HA 重启后能**自动恢复**这些监听器，避免数据丢失。

## 3. 安全、权限与错误处理 (Security & Robustness)

- **只读优先 (Read-Only Default)**：默认情况下，禁止 LLM 修改系统级配置。
- **严格白名单机制 (Action Whitelist)**：
  - 严禁操作核心组件（不可操作 `homeassistant.restart`, 无法修改用户密码等）。
  - 仅允许 LLM 操作配置中**明确列出**的域 (Domain) 或实体 (Entity)。如仅开放 `light.*`, `switch.*`, `media_player.*`。
  - 拦截器 (`Interceptor`) 必须在执行任何 step 之前进行权限校验，越权行为需直接抛出并记录警告日志。
- **容错与异常处理**：
  - LLM 接口超时、返回非 JSON 格式、返回幻觉 Entity ID 时，插件不能崩溃，需使用 `logging.error` 记录，并可选择通过 TTS 播报一条错误提示语。

## 4. 插件配置界面要求 (Config Flow & Options Flow)

必须实现完整的 HA 图形化配置流程：

1.  **Config Flow (初始安装)**：配置 `API Base URL`, `API Key`, `Model Name`。验证 Token 有效性后方可添加集成。
2.  **Options Flow (安装后配置修改)**：
    - **Prompts**: 修改 System Prompts 文本框。
    - **Input Entities**: 多选列表（Entity Selector），选择触发文本 Sensors。
    - **TTS Configuration**: 目标音箱 Entity Selector 及模式选择。
    - **Security Whitelist**: 多选 Domain 列表。
    - **History Rules**: 历史对话条数或时间限制设置。

## 5. 参考开发文档与资源

- HA Custom Component 官方指南: https://developers.home-assistant.io/docs/creating_integration_tutorial
- HA 存储持久化 (Storage): https://developers.home-assistant.io/docs/store_data_in_home_assistant
- HACS 质量标准: https://www.home-assistant.io/docs/quality_scale/#-custom
- 参考开源项目: `extended_openai_conversation`, `hass-node-red`, `xiaomi_miot_raw`

## 6. 预期文件结构与开发步骤指引

请按照以下结构和步骤构建项目：

```text
custom_components/llm_smart_assistant/
├── __init__.py           # 集成入口，初始化 async_setup_entry，挂载 coordinator
├── manifest.json         # 依赖声明与版本号 (包含 "config_flow": true)
├── const.py              # 常量定义 (DOMAIN, 默认配置项等)
├── config_flow.py        # ConfigFlow 与 OptionsFlow 实现
├── options.py            # (可选) 复杂的 OptionsFlow 逻辑分离
├── coordinator.py        # 核心逻辑：状态监听、LLM API 请求、JSON 解析
├── services.py           # HA API 执行器与白名单拦截器
├── storage.py            # 处理动态自动化的本地存储与恢复
├── translations/
│   ├── en.json
│   └── zh-Hans.json      # 支持中文配置界面
```

## 7. 开发步骤建议 (给 AI 编程助手的提示)

1.  首先创建 `manifest.json` 和 `__init__.py`，确立集成的基本骨架。
2.  实现 `config_flow.py` 和 `const.py`，处理用户在 UI 上的配置输入。
3.  开发核心协调器 (`coordinator`/核心类)，实现对目标 Text Sensor 的 Event/State 监听。
4.  实现 LLM 请求模块，构建 HTTP 请求与 JSON 解析。
5.  实现 API 执行与**白名单拦截器**模块。
6.  实现自动化监听器动态注册模块。
7.  完成 `services.yaml` 及多语言支持（`translations/en.json`, `translations/zh-Hans.json`）。
8.  所有项目内的代码的注释都用英文，所有文档都包含中英双语两个版本
9.  为了方便开发，可以在本地启动一个homeassistant的docker
