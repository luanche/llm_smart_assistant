# LLM 智能助手

[![HACS Custom Integration](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

> [English](docs/README_EN.md)

一款强大的 Home Assistant 自定义集成，将兼容 OpenAI 的 LLM 与您的智能家居连接起来，实现自然语言控制、动态自动化、TTS 语音输出和内置 AI 聊天界面。

---

## 📖 功能

| 功能                    | 说明                                                    |
| ----------------------- | ------------------------------------------------------- |
| 🤖 **多模型 LLM 支持**  | OpenAI、DeepSeek、Kimi、Gemini 等任何兼容 OpenAI 的 API |
| 💬 **内置 AI 聊天面板** | 功能完整的聊天界面，支持多轮推理                        |
| 🎤 **语音输入**         | 语音识别 + 文本传感器监听                               |
| 🗣️ **TTS 语音输出**     | 标准 TTS、小米 MIoT 和自定义模板                        |
| ⚡ **动态自动化**       | 通过自然语言创建/编辑/禁用自动化                        |
| 🔄 **多步推理**         | LLM 检查状态、执行、观察并迭代                          |
| 🔒 **安全机制**         | 领域 + 实体白名单，受限操作                             |
| 📝 **对话历史**         | 数量 + 时间窗口双重截断                                 |
| 🌐 **多语言**           | 中英文界面，可扩展                                      |
| 🏗️ **多实例**           | 多个独立的 LLM 实例                                     |

---

## 📦 安装

### HACS（推荐）

1. 在 HACS 中将此仓库添加为自定义集成仓库（HACS → 集成 → 自定义仓库）。
2. 搜索 "LLM Smart Assistant" 并安装。
3. 重启 Home Assistant。

### 手动安装

将 `custom_components/llm_smart_assistant/` 目录复制到 HA 的 `config/custom_components/` 目录，然后重启 HA。

---

## 🚀 快速开始

1. 进入 **设置 → 设备与服务 → 添加集成**。
2. 搜索 "LLM Smart Assistant"。
3. 输入 LLM API 信息：
   - **API Base URL**: `https://api.deepseek.com/v1`（或您的服务商地址）
   - **API Key**: 您的 API 密钥
   - **Model**: `deepseek-chat`、`gpt-4o-mini` 等
4. 从侧边栏打开 AI 聊天面板，或访问 `http://<your-ha>:8123/llm-chat`。
5. 开始用自然语言控制您的智能家居。

---

## ⚙️ 配置

所有设置都在一页表单中完成，可通过 **设置 → 设备与服务 → LLM Smart Assistant → 配置** 访问。

### API 设置

| 字段         | 说明                 |
| ------------ | -------------------- |
| API Base URL | LLM 服务商 API 地址  |
| API Key      | 认证密钥             |
| Model        | 模型名称             |
| Temperature  | 回复创意度 (0.0–2.0) |
| Max Tokens   | 最大回复长度         |

### 提示词

- **硬编码核心** — 关键逻辑（JSON 格式、动作、循环行为）内置且不可修改。
- **附加指令** — 用户可自定义的附加指令，追加在硬编码核心之后。支持变量：`{{ time }}`、`{{ date }}`、`{{ exposed_entities }}`

### 安全

- **允许的领域** — LLM 可控制的实体领域
- **允许的实体** — 实体白名单（留空则允许领域内所有实体）
- **允许自动化** — 启用/禁用基于 LLM 的自动化创建

### TTS（文字转语音）

| 字段         | 说明                              |
| ------------ | --------------------------------- |
| TTS 实体     | 语音输出的媒体播放器              |
| TTS 模式     | 标准、小米 MIoT 或自定义模板      |
| 自定义模板   | 自定义 TTS 服务调用的 Jinja2 模板 |
| 播报音量     | 播报前设置的音量 (0.0–1.0)        |
| 播报后静音   | TTS 后静音/开启勿扰以防回音       |
| 静音控制实体 | 独立的音量控制实体（可选）        |

### 语音输入

将 `sensor.*` 实体添加到**输入传感器**以启用语音触发对话。

### 历史记录

两个约束同时生效：

- **最大轮数** — 保留最近 N 轮对话
- **时间窗口** — 保留 N 分钟内的消息

---

## 💬 AI 聊天面板

内置 Web 界面提供：

- **多轮推理** — 处理中显示"推理中（第 N 轮）..."
- **渐进式显示** — 回复逐轮显示
- **调试弹窗** — 点击 🔧 查看完整推理过程
- **实例选择器** — 切换多个已配置的实例
- **自动化标签** — 查看、创建、编辑、启用/禁用和删除自动化
- **语音输入** — 点击 🎤 使用浏览器语音识别
- **移动端适配** — 响应式布局

---

## 🔧 服务调用

| 服务                | 说明                |
| ------------------- | ------------------- |
| `process_input`     | 发送文本给 LLM 处理 |
| `create_automation` | 创建动态自动化      |
| `update_automation` | 编辑自动化          |
| `toggle_automation` | 启用或禁用自动化    |
| `remove_automation` | 删除自动化          |
| `get_automations`   | 列出所有自动化      |

---

## ⚡ 动态自动化

使用自然语言创建自动化：

> "当温度高于30度时打开空调"
> → 创建: `sensor.living_room_temperature > 30` → 打开空调

自动化会持久化保存，并使用 HA 的事件系统进行实时状态变化检测。

---

## 📁 文件结构

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
│   ├── index.html        # AI 聊天界面
│   └── chat.js           # 侧边栏面板组件
└── translations/
    ├── en.json
    └── zh-Hans.json
```

---

## 📋 系统要求

- Home Assistant 2024.6+
- Python 3.12+
- 兼容 OpenAI 的 LLM API 密钥

---

## 📄 许可证

MIT
