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

### 调试 Dashboard

新环境初始化时运行一次（幂等），创建 `/llm-devices` 调试面板（虚拟设备状态 + LLM 调试传感器）：

```bash
python3 .pi/skills/llm-test/setup_dashboard.py
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
| `toggleAutomation()`          | 启用/禁用自动化（乐观 UI，即时反馈）        |
| `showAddSheet()`              | 打开添加自动化底部弹窗        |
| `showEditSheet()`             | 打开编辑底部弹窗（实体/条件/动作）        |
| `showDeleteConfirm()`         | 打开删除确认底部弹窗        |
| `initHistory()`               | 加载聊天历史（recorder API，滚动到顶懒加载） |

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
| 历史记录读 HA recorder（不缓存）        | 重启后历史仍在；所有输入来源统一由 `sensor.llm_last_input` 记录（聊天面板/服务调用/语音传感器），与回复 sensor 合并成时间线 |
| 历史过滤跳过中间轮次                    | recorder 对相同 state 去重，最终回复可能与上轮相同；用相邻去重而非 in_progress 过滤 |
| 历史懒加载用 before 游标                | 时间倒序 + 游标分页，滚动到顶加载更早记录；游标需 URL 编码（`+` → 空格） |
| 自动化多触发 triggers 数组              | `[{entity_id, condition}]` 或 `[{type: time, time}]`；保留 entity_id/condition property 兼容旧 storage，自动迁移 |
| 复合表达式 expression                  | 触发索引用数字（`(0 and 1) or 2`），安全递归下降解析器（无 eval）；支持 AND/OR/括号/优先级；无 expression 时按 trigger_logic 回退 |
| AND 逻辑实时检查全部触发源              | 任一触发源变化时检查**所有** entity trigger 当前状态（而非历史状态），避免跨事件状态跟踪复杂度 |
| 时间触发每日自动重注册                 | `async_track_point_in_time` 触发后若非 one-shot/未禁用则注册下一天，实现"每天 21:00"式长期定时 |
| schedule 计划调度（once/daily/weekly/monthly）| Task 7c：`_compute_next_fire` 计算下一次触发（weekly 扫 7 天、monthly 扫 62 天跨月边界、once 精确 datetime 触发后不再重复）；`_register_time_trigger` 按 schedule 重注册，无未来时间则停止；LLM 可用自然语言创建（"每个星期一…"→weekly weekdays:[1]） |
| one-shot 触发后自毁                    | 执行完成即 `async_remove_automation`，适用于"1分钟后关空调"等一次性规则 |
| 执行记录环形缓冲 30 条                | 每次触发写入 time/trigger/result/ok/steps，随自动化持久化，重启保留；UI 专属 debug 弹窗按 automation 显示 |
| 多输出设备 tts_entities 列表           | Task 4b：可配多个 TTS 设备（含区域）；prompt 注入 `## Output devices`（entity_id/name/area CSV），LLM 响应 JSON 可加 `output_device` 选择最近设备；兼容旧 `tts_entity_id`（首设备作默认，旧配置自动镜像进列表） |
| 输入来源标记 + 区域解析                | `process_input` 支持 `source_entity`；`_get_area_name` 用 entity registry `area_id` → area registry 名称，注入 `## Input source`；LLM 按用户所在区域选输出设备；AI Chat/service_call 不 TTS（浏览器播报） |
| output_device 白名单校验              | 仅接受配置内设备（`in self.tts_entities`），防止 LLM 幻觉设备 ID；无效回退默认设备 |
