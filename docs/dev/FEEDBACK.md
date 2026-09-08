# HACS Review 反馈 — 待修复问题清单

> 来源：HACS 审核反馈（PR #30），2026-08-14
> 状态：⏳ 待修复 | 优先级：🔴 严重 / 🟠 中 / 🟡 低

---

## 🔴 S1: ChatPanelView 暴露长期访问令牌

### 问题
`ChatPanelView` 注册于 `/api/llm_smart_assistant/chat_panel`，设置 `requires_auth = False`，在 `get` 处理器中将用户的长期访问令牌（`access_token` 配置项）直接注入到 HTML 中：

```python
# __init__.py
class ChatPanelView(HomeAssistantView):
    url = "/api/llm_smart_assistant/chat_panel"
    name = "api:llm_smart_assistant:chat_panel"
    requires_auth = False  # <-- 无认证

    async def get(self, request):
        if access_token:
            script = f'<script>window.CONFIGURED_ACCESS_TOKEN={json.dumps(access_token)};</script>'
            current_html = current_html.replace("</head>", script + "</head>")
```

任何能访问 HA HTTP 端口的人（无凭据即可）请求此 URL 即可获得完整 API 控制权限的令牌。`require_admin=True` 设置在侧边栏面板上，但此路由绕过它。

### 审核意见
删除 `requires_auth = False`，停止将令牌注入 HTML。前端已有 `localStorage`、PostMessage 等 token 发现渠道。

### 评估
✅ **按审核意见修。** 改动小且安全，不影响功能。

### 涉及文件
- `custom_components/llm_smart_assistant/__init__.py`（ChatPanelView）

---

## 🔴 S2: 其他三个 View 也无认证

### 问题
| View | URL | 风险 |
|------|-----|------|
| `ChatSuggestionsView` | `/api/llm_smart_assistant/suggestions` | 匿名者可调用 LLM，消耗用户 API 额度 |
| `ChatHistoryView` | `/api/llm_smart_assistant/history` | 返回 7 天对话历史给匿名调用者 |
| `ChatJSView` | `/api/llm_smart_assistant/chat_js` | 无直接数据泄露风险，但应统一认证 |

### 审核意见
三个 View 都删除 `requires_auth = False`，使用默认的 `True`。

### 评估
✅ **按审核意见修。** 简单直接。

### 涉及文件
- `custom_components/llm_smart_assistant/__init__.py`（ChatSuggestionsView、ChatHistoryView、ChatJSView）

---

## 🔴 S3: 令牌通过 URL 参数传递 + PostMessage 通配符 origin

### 问题
```javascript
// chat.js
const src = '/api/llm_smart_assistant/chat_panel' + (token ? '?auth_token=' + encodeURIComponent(token) : '');
// ...
event.source.postMessage({ type: '__llm_auth_token__', ... }, '*');  // 通配符 origin
```

令牌在 URL 中会落入日志、浏览历史、Referer 头。PostMessage 通配符也不安全。

### 审核意见
删除 `?auth_token=` 参数传递方式，将 `postMessage` 的 `'*'` 改为明确的目标 origin。

### 评估
✅ **按审核意见修。** 改动小，安全提升明显。

### 涉及文件
- `custom_components/llm_smart_assistant/panel/chat.js`

---

## 🟠 S4: hacs.json 声明的 HA 最低版本过低

### 问题
`hacs.json` 声明 `"homeassistant": "2024.6.0"`，但 `config_flow.py` 中 `OptionsFlow` 使用了 `self.config_entry` 属性（在 `OptionsFlow` 上直到 HA 2024.12.0 才存在）。在 2024.6 ~ 2024.11 上打开 Configure 会抛出 `AttributeError`。

### 审核意见
将 `hacs.json` 中的 `homeassistant` 提升到 `2024.12.0`。不要手动赋值 `self.config_entry`（该 setter 在 2025.12.0 中被移除）。

### 评估
✅ **按审核意见修。** 一行改动，无副作用。

### 涉及文件
- `hacs.json`

---

## 🟠 S5: call_service 无 target 时绕过实体白名单

### 问题
```python
# services.py
allowed_entities = self.coordinator.entities_whitelist
if allowed_entities and target:  # <-- target 为空时跳过检查
    # ... 检查 target 中的实体是否在白名单内
```

当 LLM 输出的 step 没有 `target` 字段（如 `{"action":"call_service","domain":"light","service":"turn_off"}`），白名单检查被跳过，服务会对该域下**所有实体**生效。

### 审核意见
当实体白名单已设置但 `target` 为空时，拒绝调用或抛出拦截错误。

### 评估
✅ **按审核意见修，但实现细节要精确。** 

当 `entities_whitelist` 有值且 `target` 为空时，才拦截。如果只设了 `domains_whitelist`（没设 `entities_whitelist`），无 target 的调用是合法的。所以拦截条件应该是：

```python
if allowed_entities:
    if not target:
        raise StepInterceptionError("Entity whitelist requires a specific target entity")
    # ... 检查 target 中的实体
```

### 涉及文件
- `custom_components/llm_smart_assistant/services.py`

---

## 🟠 S6: async_unload_entry 不清理 sensor 平台

### 问题
`async_unload_entry` 没有调用 `async_forward_entry_unload`，导致重载集成后旧的 sensor 仍注册在已失效的 coordinator 上，重复 setup 会添加第二组 sensor。

### 审核意见
在 `async_unload_entry` 中添加 `await hass.config_entries.async_forward_entry_unload(entry, Platform.SENSOR)`。

### 评估
✅ **按审核意见修。** 一行改动，不修的话重载集成会残留僵尸 sensor。

### 涉及文件
- `custom_components/llm_smart_assistant/__init__.py`

---

## 🟠 S7: panel 中 innerHTML 未转义 LLM 可控值

### 问题
三处 LLM 可控值通过 `innerHTML` 插入，未使用 `escapeHtml`：

1. **表达式 (`expr`) 在 trigHtml 构建中**：`expr` 中的非数字/非逻辑符字符直接通过替换后进入 `innerHTML`
2. **weekdays 值**：当 `w` 不在 1-7 范围时，原始值直接输出，未转义
3. **days_of_month 值**：虽然通常是数字，但未转义

这些值由 `async_create_automation` 持久化存储，攻击者可通过 prompt injection 让 LLM 生成恶意值。

### 审核意见
对这三处使用 `escapeHtml` 转义。

### 评估
🤔 **方向对，但更好的做法是前后端双重防护：**

审核意见只建议前端转义，我认为可以做得更彻底：

1. **后端**（`async_create_automation`/`async_update_automation`）：创建时校验字段合法性
   - `expression`：只允许 `[0-9\s()andorANDOR]`，非法值直接拒绝
   - `weekdays`：只允许 1-7 整数，超出范围拒绝
   - `days_of_month`：只允许 1-31 整数，超出范围拒绝
   - 这是**根本防护**——恶意数据根本存不进来
2. **前端**：`escapeHtml` 兜底，防止存储层被绕过（如直接改 storage 文件）
   - `expr` 在用于 `innerHTML` 前先 `escapeHtml`，再替换 `and`/`or` 为加粗标签
   - `weekdays` 和 `days_of_month` 的 fallback 值用 `escapeHtml`

双层防护比单层前端转义更可靠。

### 涉及文件
- `custom_components/llm_smart_assistant/coordinator.py`（后端校验）
- `custom_components/llm_smart_assistant/panel/index.html`（前端转义）

---

## 🟡 S8: 多实例下 per-entry 服务互相覆盖

### 问题
`chat`、`create_automation`、`update_automation`、`get_automations` 四个服务按实例注册，但注册时通过闭包捕获了单个 `coordinator`。第二个实例 setup 时用新实例的 handler 覆盖了第一个实例注册的服务，所有四个服务始终作用于**最后加载的实例**。

`process_input` 和 `toggle_automation` 已正确处理（全局注册 + `entry_id` 路由），但这四个服务没有。

### 审核意见
为这四个服务添加 `entry_id` 参数，或将其改为全局注册 + entry_id 路由（与 `process_input` 相同模式）。

### 评估
✅ **方向对，但改动量不小。**

`process_input` 的全局注册 + `entry_id` 路由模式是成熟的，照搬即可。但 `update_automation` 和 `get_automations` 的 handler 直接操作 `coordinator._automations` 和 `coordinator._disabled_automations_set`，改造时需要：
1. 将这些服务改为全局注册（只在首次 setup 时注册一次）
2. 每个 handler 通过 `entry_id` 参数从 `hass.data[DOMAIN]` 查找对应的 coordinator
3. 再委托给该 coordinator 的方法

这样多实例就能正确路由到各自的自动化数据。

### 涉及文件
- `custom_components/llm_smart_assistant/__init__.py`

---

## 修复优先级与方案总结

| 序号 | 问题 | 优先级 | 方案 | 文件数 | 预估改动量 |
|------|------|--------|------|--------|-----------|
| 1 | S1 ChatPanelView 令牌泄露 | 🔴 | 按审核意见 | 1 | ~5 行 |
| 2 | S2 其他三个 View 无认证 | 🔴 | 按审核意见 | 1 | ~3 行 |
| 3 | S3 URL 令牌 + PostMessage 通配符 | 🔴 | 按审核意见 | 1 | ~5 行 |
| 4 | S5 白名单绕过 | 🟠 | 按审核意见，精确定义拦截条件 | 1 | ~5 行 |
| 5 | S7 innerHTML 注入 | 🟠 | **双重防护**：后端校验 + 前端转义 | 2 | ~30 行 |
| 6 | S6 卸载不清理 sensor | 🟠 | 按审核意见 | 1 | ~2 行 |
| 7 | S4 HA 最低版本 | 🟡 | 按审核意见 | 1 | ~1 行 |
| 8 | S8 多实例服务覆盖 | 🟡 | 按审核意见，全局注册 + entry_id 路由 | 1 | ~80 行 |

### 修复批次建议

| 批次 | 问题 | 预计耗时 | 说明 |
|------|------|---------|------|
| **第一批** | S1 + S2 + S3 | ~10 分钟 | 安全漏洞，改动最小，优先上线 |
| **第二批** | S5 + S6 + S7 | ~30 分钟 | 安全/功能缺陷，改动中等 |
| **第三批** | S4 + S8 | ~1 小时 | S4 一行，S8 需要较大重构，可延后 |