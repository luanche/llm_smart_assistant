# 开发指南

> [English](DEVELOP_EN.md)

---

## 🚀 开发环境

```bash
# 启动 HA（含集成）
docker compose up -d

# 查看日志
docker compose logs -f

# 重启
docker compose restart

# 停止
docker compose down
```

---

## 📁 代码结构

```
custom_components/llm_smart_assistant/
├── __init__.py           # 入口、服务、面板注册
├── manifest.json         # 依赖和版本
├── const.py              # 常量、默认提示词
├── config_flow.py        # ConfigFlow（初始 4 字段）+ 单页 OptionsFlow（24 个字段）
├── coordinator.py        # 核心：LLM API、ReAct 循环、自动化
├── services.py           # 步骤执行器（含白名单拦截）
├── sensor.py             # LLMLastResponseSensor + LLMDebugRawSensor
├── services.yaml         # 服务定义
├── icons.json
├── brand/
│   ├── icon.png
│   └── logo.png
├── panel/
│   ├── index.html        # AI 聊天界面（纯 JS 多语言）
│   └── chat.js           # 创建 iframe 的 LitElement 包装
└── translations/
    ├── en.json
    └── zh-Hans.json
```

---

## 🔄 热重载

**面板文件 (HTML/JS)**: `panel/index.html` 和 `panel/chat.js` 每次请求都从磁盘读取，编辑后刷新浏览器即可——**无需重启 HA**。

**Python 修改 (`*.py`)**: 需要重启 HA：

```bash
docker compose restart
```

---

## 💬 AI 聊天面板

### 架构

聊天面板是纯 HTML/JS 单页应用，通过 iframe 加载在 HA 侧边栏中。

```
HA 侧边栏
  → panel_custom → chat.js (LitElement)
    → <iframe src="/api/llm_smart_assistant/chat_panel">
      → index.html（完整界面）
```

### 多语言系统

面板使用 `LANGUAGES` 对象 + `t()` 翻译函数：

```javascript
const LANGUAGES = {
  en: { title: 'AI Chat', ... },
  zh: { title: 'AI 聊天', ... },
  // 在此添加新语言
};

// JS 中使用
t('title')  // → 'AI Chat' 或 'AI 聊天'

// HTML 中使用（自动应用）
<button data-i18n="addAuto"></button>
```

**添加新语言：**

1. 在 `LANGUAGES` 对象中添加包含所有键的条目。
2. `applyI18n()` 自动根据浏览器语言加载。
3. 回退链: 完整语言 → 语言根 → `en`。

### Token 获取（iframe 环境）

iframe 通过多个回退通道获取 HA 认证令牌：

1. 后端注入的配置令牌（`window.CONFIGURED_ACCESS_TOKEN`，来自配置项 `access_token`）
2. `chat.js` 通过 URL 参数传递 (`?auth_token=...`)
3. 从 `localStorage['hassTokens']` 读取（同源）
4. 与父窗口 PostMessage 握手
5. 回退到手动输入

### 关键函数 (index.html)

| 函数                          | 用途                           |
| ----------------------------- | ------------------------------ |
| `t(key)`                      | 翻译键值                       |
| `applyI18n()`                 | 应用到所有 data-i18n 元素      |
| `callAPI(method, path, body)` | 带认证的 HA REST API 封装      |
| `sendMessage()`               | 发送输入，通过 WebSocket 订阅传感器并渐进显示 |
| `subscribeEntity()`           | 通过 HA WebSocket API 订阅实体状态变化        |
| `refreshAutomations()`        | 获取并渲染自动化卡片           |
| `toggleAutomation()`          | 启用/禁用自动化                |
| `showEditModal()`             | 打开编辑弹窗（3 个字段）       |
| `showAddModal()`              | 打开添加自动化弹窗             |

---

## 🔍 本地化审核

提交前运行以检查所有本地化文件。

```bash
# 运行审核
python3 .pi/skills/i18n-audit/check.py

# 保存基线
python3 .pi/skills/i18n-audit/check.py --save-baseline

# 与基线对比
python3 .pi/skills/i18n-audit/check.py --diff
```

检查内容：

- `panel/index.html` — i18n 键覆盖、硬编码字符串
- `LANGUAGES.en` ↔ `LANGUAGES.zh` — 键完整性
- `t('key')` 调用 — 所有引用的键都有效
- `data-i18n` 属性 — 所有 data-i18n 属性引用有效键
- `translations/en.json` ↔ `translations/zh-Hans.json` — 键完整性
- `config_flow.py` — 硬编码标签 vs 翻译键
- `const.py` — 默认提示词存在
- `services.yaml` — 服务描述存在

---

## 🔄 集成流程

### 消息处理

```
用户输入（聊天界面 / 服务调用 / 文本传感器）
  → coordinator._async_process_user_input()
    → _build_context()（时间、日期、实体 CSV）
    → _async_query_llm()（API 调用带重试和退避）
    → 解析 JSON 响应
    → _execute_steps()（验证 + 执行）
    → 更新 sensor.llm_last_response（逐轮更新）
    → 重复直到 steps 为空或达到最大迭代
  → 最终 TTS 文本存储
```

### 自动化触发流程

```
实体状态变化
  → async_track_state_change_event 触发
  → _async_handle_automation_event()
    → 检查禁用列表
    → 调用 LLM
    → 解析响应 → 执行步骤
```

### 服务注册

`process_input` 和 `toggle_automation` **全局注册**（首次设置时注册一次）。

其他服务 (`create_automation`、`remove_automation`、`get_automations`、`update_automation`、`chat`) 按**实例注册**。`chat` 服务由聊天面板后端使用，同步返回 LLM 响应。

---

## 🎯 关键设计决策

| 决策                                    | 理由                                                 |
| --------------------------------------- | ---------------------------------------------------- |
| `process_input` 全局注册                | 多实例注册同一服务，通过 entry_id 路由               |
| `toggle_automation` 全局注册            | 同理——需要 entry_id 找到正确的协调器                 |
| 面板文件每次请求读取                    | 支持 HTML/JS 热重载而无需重启 HA                     |
| `data-i18n` 属性模式                    | 添加新字符串只需一个 HTML 属性 + 一个 LANGUAGES 条目 |
| 数量和时间的双重限制                    | 同时应用两个约束以实现更精确的历史控制               |
| WebSocket 订阅替代轮询                  | 实时推送 LLM 渐进回复，降低延迟与请求开销            |
| LLM 格式使用 entity_id/condition/prompt | 简单、对 LLM 友好的结构                              |
| 禁用移除监听器                          | 不同于标记检查，这能真正停止事件触发                 |
