# LLM Smart Assistant — 任务清单

> 任务追踪（进 git，方便 track 和协作）。完成后在对应任务前打 ✅ 并补充实现方案。
> 建分支前遵守 AGENTS.md 规则：fetch master、确认旧分支已合并、从最新 master 建分支。

---

## 🐛 Bug 修复（优先）

### Task 1: 重启后重复执行最后指令
- **现象**: 每次重启 HA，AI 都会执行之前最后一次的指令
- **类型**: bug | **分支**: `fix/no-reexec-on-restart`
- **分析**: 大概率是启动加载 storage 后，input sensor 的 `async_track_state_change_event` 对恢复的状态又触发了一次，或自动化监听器注册时对当前状态误触发。需要加"启动时跳过首次触发"逻辑
- **优先级**: 🔴 高（会产生实际副作用）
- **状态**: ✅ 已完成（v1.2.2，PR #9）
- **实现方案**:
  1. **根因**: `_async_handle_sensor_change` 未检查 `old_state`。HA 重启后输入传感器（如小米 conversation sensor）以旧值重新注册，`old_state=None` 的事件被当成新输入处理。自动化处理器 `_async_handle_automation_event` 早已有此检查，输入处理器漏了。
  2. **修复一（状态恢复跳过）**: `old_state is None` 时视为状态恢复/重注册，将文本记录到 `_last_states` 但不处理。这样重启恢复的旧指令不会重复执行，后续相同文本的幻影更新也会被重复检测拦截。
  3. **修复二（`_last_states` 持久化）**: 存入 storage（`last_input_states` 字段），覆盖"重启后 sensor 先 unavailable 再恢复旧值"（`old_state=unavailable` 不为 None）的幻影触发场景。更新时走已有的 debounced save。
  4. **前置改进（为 Task 8 铺路）**: storage 改为按实例隔离——`Store` key 从共享的 `llm_smart_assistant.storage` 改为 `llm_smart_assistant.storage_{entry_id}`，首次加载自动从 legacy 共享 key 迁移。避免多实例的 automations/history/last_input_states 互相覆盖（多中枢 sensor 不共用的前置）。
  5. **行为变化（注意）**: 首次通过 API 为一个不存在的实体 set state 时（`old_state=None`）会被当作恢复跳过——第二次 set 才生效。测试用的预定义传感器（如 `sensor.test_voice_input`）不受影响。
- **验证**: 指令处理 ✓ → 重启零重复执行 ✓ → 重启后新指令正常 ✓ → legacy storage 迁移日志 ✓

### Task 2: Release pipeline 的 changelog 没写进 Release
- **现象**: 打包后的 changelog 没有写到 release 的 change 里面
- **类型**: bug | **分支**: `fix/release-notes-changelog`
- **分析**: `release.yml` 生成 RELEASE_NOTES 时取 `PREV_TAG` 的时机不对——bump 后先打了新 tag，再 `git tag --sort=-creatordate | head -1` 拿到的就是刚打的新 tag，导致 `git log "${PREV_TAG}..HEAD"` 范围为空
- **状态**: ✅ 已完成（v1.2.3，PR #10）
- **实现方案**: 在 `Bump version` 步骤（打 tag 之前）预计算 `PREV_TAG` 并通过 GitHub Actions output 传递，changelog 和 release notes 步骤都复用同一个值，不再在打 tag 后重新计算。

### Task 2b: input_text 实体无法选为输入传感器
- **现象**: options flow 的 input_entities 选择器不支持 `input_text` domain，选了不生效
- **类型**: bug | **分支**: `fix/input-entities-allow-input-text`
- **状态**: ✅ 已完成（v1.2.4，PR #11）
- **实现方案**: 在 config_flow 的 input_entities 选择器的 include_entities / domain 白名单中补充 `input_text` 域，确保该类型的实体可被选作输入传感器。

---

## 🎤 语音输入体验（AI Chat 面板）

### Task 3: 按住说话（PTT）交互重做
- **类型**: feat + bug | **分支**: `feat/ptt-voice-ux`
- **包含**:
  - [x] 按住说话按钮的文本不太对（bug）
  - [x] 按住说话上滑取消
  - [x] 语音输入内容不要在按钮上显示（会被挡住），改在聊天窗口显示 + "正在输入"动画
  - [x] AI chat 语音输入使用浏览器 speechSynthesis 播报回复（后端跳过 HA TTS）
- **实现方案**:
  1. **i18n 修正**: `holdToSpeak` 从 "Tap to speak" / "点击说话" 改为 "Hold to speak" / "按住说话"；新增 `releaseToCancel` / `slideUpCancel` 键
  2. **上滑取消**: 在 `#voiceHoldBtn` 上添加 `onpointermove` / `onpointerleave` 监听，记录按下时的 `clientY`；当向上滑动超过 60px 时进入 `cancel-state`（按钮变红 + 显示 "Release to cancel"），松开时触发 `abort()` 取消录制
  3. **语音气泡**: 录制时在聊天区创建一个 `.voice-bubble` 临时元素（带 `.voice-wave` 呼吸动画条 + 闪烁光标的 interim 文本），每帧将识别结果更新到气泡内；取消或完成时自动移除
  4. **source 标记 + browser TTS 前置**: `sendMessage()` 新增 `fromVoice` 参数，为语音输入在请求体中加 `source:'voice'`；后端 `__init__.py` 的 `async_process_input` 接收 `source` 字段并传给 `coordinator._async_process_user_input`；协程签名扩展为 `source: str = ""`；前端 `handleState` 回调在 `fromVoice=true` 时调用 `window.speechSynthesis.speak()` 做浏览器播报（后续 Task 4a 完成完整的 TTS 路由）
- **分析**: 沿用微信 PTT 交互模式；识别中在聊天区加一个带呼吸动画的"临时消息气泡"，识别完成替换为正式消息；TTS 回复需要"输入来源"标记（voice/text）传给后端决定是否 TTS
- **状态**: ✅ 已完成（v1.3.0，PR #12）
- **后续修复**: `fix/ptt-voice-mobile`（v1.3.1）———上滑取消适配手机（去掉了 `onpointerleave` 误触释放，改用 `setPointerCapture` 跟踪指针；三态文字互斥；渐进式取消进度条；蓝底红点录制图标；取消态隐藏图标显示动画箭头）

---

## 🗣️ TTS 输出路由

### Task 4: 输出设备决策 + 多设备 I/O
- **类型**: feat | **分支**: `feat/multi-device-io-routing`
- **包含**:
  - [x] 4a: AI Chat（文字 + 语音）都不调 HA TTS 输出设备；语音回复改由浏览器 `speechSynthesis` 播报
  - [x] 4b: 允许配置多个输入设备和输出设备提供给模型；用户用某设备输入时，由模型根据设备位置决定最合适的输出设备
- **分析**: 输入来源标记（`chat_ui` / `service_call` / 具体 sensor entity_id）决定默认是否 TTS；多输出设备需要配置结构改为列表 + prompt 中注入设备位置信息（area），模型在响应 JSON 中指定 `output_device`。建议拆两步：先 4a（chat 不 TTS），再 4b（多设备路由）
- **4a 实现方案**（`fix/chat-tts-browser`，v1.3.3）:
  1. **后端** `coordinator.py`: `entity_id` 为 "service_call" 或 "chat_ui" 时无条件跳过 `_async_speak_tts`（之前版本只对 text 跳过、voice 保留，现改为两者都跳过）
  2. **前端** `panel/index.html`: `sendMessage` 的 `handleState` 回调中，当 `fromVoice=true` 且收到 TTS 文本时，调用 `window.speechSynthesis.speak()` 通过浏览器播报，语音设为当前界面语言
- **4b 实现方案**（`feat/multi-device-io-routing`，v1.8.0，PR #23）:
  1. **const.py**: 新增 `CONF_TTS_ENTITIES`（多输出设备列表）、`CONF_TTS_INPUT_ENTITY`；HARDCODED prompt 增加 `## Output devices`（设备+区域 CSV）与 `## Input source`（用户输入来源+区域）段，响应 JSON 支持可选 `output_device` 字段（默认省略则用首设备）
  2. **coordinator.py**: `tts_entities` property（多设备，回退旧 `tts_entity_id`，同时查 `_data` 兼容历史存储）；`_get_area_name` 真正实现（entity registry `area_id` → area registry `async_get_area` 名称）；`_build_output_devices_info` / `_build_input_source_info` 构建 prompt 注入；`_output_device_from_rounds` 提取 LLM 选择（仅接受配置内的设备）；`_async_speak_tts(text, output_device="")` 支持显式路由，无效回退默认；自动化触发也透传 `output_device`
  3. **config_flow.py**: options 表单新增多设备选择器（`CONF_TTS_ENTITIES` multiple=True，保留旧单设备字段）；保存时同步 `tts_entity_id`=列表首个，旧单设备自动镜像进列表
  4. **__init__.py**: `process_input` 服务新增 `source_entity` 参数（输入设备，用于位置路由），schema 加 `vol.Optional("source_entity")`
  5. **前端** `panel/index.html`: debug 弹窗 round 显示 `输出设备：<entity_id>`（`debugOutputDevice` i18n key）
  6. **测试**: 卧室输入（sensor.test_voice_input area=卧室）→ LLM 选择卧室音箱并 TTS ✓；无来源 service_call → 不 TTS ✓；自动化触发 → 回退默认设备 ✓；区域解析（entity registry area_id → area 名称）✓；prompt 正确注入 Output devices / Input source ✓；debug 弹窗显示路由 ✓
- **状态**: ✅ 已完成（v1.8.0，PR #23）

---

## 📱 AI Chat 移动端 UI

### Task 5: 移动端可用性优化
- **类型**: feat | **分支**: `feat/mobile-ui-polish`
- **包含**:
  - [x] 顶部"聊天/自动化"tab 按钮太小，手机端整体字体/按钮偏小
  - [x] 提供复制 AI Chat 页面链接的地方（方便单独用浏览器打开）
  - [x] 聊天窗口左右滑切换聊天/自动化页面（注意不要和 HA 侧边栏手势冲突）
  - [x] Debug 弹窗：Actions 放 Prompt 前面，拉取最新 `full_response` 避免数据过期
- **实现方案**:
  1. **触摸优化**: 移动端 `@media (max-width: 640px)` 中 `.pill-btn` 的 padding 加大到 8px/14px，`min-height: 40px`；`.debug-btn`/`.share-btn` 设为 `min-width: 44px; min-height: 44px`；`.suggestion-btn` 设 `min-height: 44px`
  2. **复制链接**: header 加 🔗 按钮，调用 `navigator.clipboard.writeText()` 复制当前 URL；成功时弹出 `#toast` 浮层 2 秒后自动消失
  3. **滑动手势**: 在 `#chatOuter` 和 `#autoContainer` 上监听 `touchstart`/`touchend`；水平滑动 >50px 且纵向偏移 < 横向 50% 时触发切换；左侧 20px 起始不响应（防 HA 侧边栏冲突）
  4. **滑页动画**: `#chatTab` 和 `#autoTab` 包裹在 `#tabSlider` 中，用 `transform: translateX` + `transition: 0.3s cubic-bezier` 实现顺滑过渡；CSS class `slide-chat`/`slide-auto` 控制位置
  5. **Debug 弹窗**: 打开时先通过 API 拉 `sensor.llm_last_response` 的 `full_response` 获取最新动作数据，再拉 `sensor.llm_debug_raw` 的 `prompt` 显示在下方；避免依赖内存变量导致过期
  6. **FAB 修复**: `.fab` 默认 `display: none`，切到 Automations 页时由 `switchTab` 设为 `flex`，避免首次加载时漏出
- **分析**: 整体过一遍 touch target（≥44px）和字号；滑动手势在内容区域做、加边缘 dead zone（左侧 ~20px 不响应）避免与 HA 侧边栏冲突
- **状态**: ✅ 已完成（v1.4.0，PR 已合并；v1.4.1 修复实例选择器——自定义下拉框替代原生 select，修复 z-index 遮挡）

---

## 💬 聊天历史

### Task 6: 历史聊天记录显示
- **类型**: feat | **分支**: `feat/chat-history-panel`
- **包含**:
  - [x] 生成的实体除了 LLM Last Response，也记录最后一次输入内容（`last_input` / `last_input_entity` / `last_input_time` 属性）
  - [x] AI Chat 显示历史聊天记录——用 HA recorder 的 sensor 历史（不缓存），多个输入设备 + AI Chat 的记录都显示，懒加载分页
- **实现方案**（v1.6.0）:
  1. **后端 `coordinator.py`**: `_async_process_user_input` 记录 `last_input` / `last_input_entity` / `last_input_time`（dt_util.now().isoformat()）
  2. **`sensor.py`**: 新增 `LLMLastInputSensor`（`sensor.llm_last_input_<实例>`，unique_id `{entry_id}_last_input`，state=last_input，attributes 含 source_entity/input_time）——**所有来源的用户输入**（聊天面板 service_call、语音输入 sensor）都会写入它，recorder 记录其状态历史作为聊天历史的 user 消息来源；`LLMLastResponseSensor.extra_state_attributes` 暴露三个 last_input 属性方便 dashboard 查看
  3. **后端 `__init__.py`**: 新增 `ChatHistoryView`（`GET /api/llm_smart_assistant/history?entry_id=&before=&limit=`）——用 HA recorder 的 `get_significant_states` 读取本实例 last_response sensor（assistant 消息）+ last_input sensor（user 消息）；assistant 消息跳过中间轮次（相邻重复文本合并，recorder 对相同 state 去重导致最终回复可能缺失，所以不依赖 in_progress 过滤）；按时间倒序 + `before` 游标分页（`limit` 默认 20 最大 50，7 天窗口）
  4. **前端 `index.html`**: `initHistory()` 首次加载最近 20 条渲染在聊天区；滚动到顶（scrollTop<30）时用 `historyBefore` 游标懒加载更早记录并 prepend；切换实例时清空重载；历史消息带 `.history-msg` class 便于样式区分；**全局实时订阅** `startGlobalSubscription()`（subscribeEntities 监听 last_input + last_response）——外部输入（语音传感器、服务调用）实时显示 user 气泡和 assistant 回复，无需刷新；`_sendingFromPanel` 标志避免与面板自身发送重复显示
  5. **边界处理**: before 游标 URL 编码（`+` 会被解析为空格需 encodeURIComponent）；无法解析的游标返回空避免死循环；epsilon 微秒偏移避免边界重复
  6. **时序修复**（合入前补充）: ① `_async_process_user_input` 设置 last_input 后立即 `_async_notify_listeners()`，否则 last_input sensor 要等 LLM 首轮响应才更新，导致 user 消息时间戳错误（晚于真实输入）；② 历史合并不再依赖时间顺序/`in_progress` 属性（recorder 会去重最终回复），改用每条 assistant 记录的 `last_input` 属性作为分组键——assistant 按"它响应的用户输入"分组，每组保留最后一条不同文本，然后插到对应 user 消息之后；无 last_input 属性的旧记录作为 orphan 按时间排序；③ **面板显示旧回复 bug**：立即 notify 时 last_response 还是上一轮的（in_progress=False），前端 WS 会误判完成而显示上次回复——修复为 notify 前先置 `in_progress=True` + `last_response=None`，新消息发送后 sensor 立即清空，前端只显示新回复
- **分析**: 数据源用 HA recorder（持久化，重启后历史仍可读）；多个输入设备 + AI Chat 的记录统一按时间线合并；懒加载用时间游标向上翻页
- **状态**: ✅ 已完成（v1.6.0，PR #21）

---

## ⚡ 自动化引擎增强

### Task 7: 自动化能力升级（核心，改动最大）
- **类型**: feat | **分支**: `feat/automation-upgrade`
- **包含**:
  - [x] 一条自动化允许配置多个传感器，条件用逻辑运算符连接（AND/OR）；且不只 sensor，开关等实体、当前时间等也可作为监听源
  - [x] 自动化分一次性/长期，由模型根据用户输入决定（如"1分钟后关闭空调"=临时）
  - [x] Automation 的执行也要记录，方便回溯 debug
  - [x] AI Chat Automation 界面点 debug 按钮，显示该 automation 的 debug 信息而不是 chat 的
- **分析**: 触发模型从"单实体+条件"升级为"多触发源+逻辑表达式"；一次性自动化用 `async_track_point_in_time` 或触发后自毁；执行记录存 storage（环形缓冲，保留最近 N 条），debug 弹窗按来源显示。建议拆 2 个 PR：先多触发源，再一次性功能+执行记录
- **状态**: ✅ 已完成（v1.7.0，PR #22）
- **实现方案**:
  - `DynamicAutomation` 升级: `triggers` 数组（每项 `{entity_id, condition}` 或 `{type: time, time: HH:MM}`）+ `trigger_logic` (and/or) + `expression`（复合布尔表达式，如 `"(0 and 1) or 2"`，触发索引用数字）+ `one_shot` + `records`（环形缓冲 30 条）; 保留 `entity_id`/`condition` property 做向后兼容，旧 storage 数据自动迁移; 无 expression 时按 trigger_logic 回退（全 AND/任意 OR）
  - 监听: 每个 entity trigger 单独注册 `async_track_state_change_event`; time trigger 用 `async_track_point_in_time` 每日重复（非 one-shot/未禁用时触发后自动重注册下一天）; 表达式用安全递归下降解析器 `_TriggerExpressionParser`（无 eval，支持 AND/OR/括号/优先级），任一触发源变化时求整个表达式
  - one-shot: 执行后 `async_remove_automation` 自毁（日志验证）; 时间 one-shot 如"1分钟后关空调"
  - 执行记录: `_async_process_automation_trigger` 每次执行写 record (time/trigger_entity/trigger_state/result/ok/steps)，持久化到 storage，重启保留
  - LLM prompt (HARDCODED): create_automation 支持 `triggers` 数组 + `trigger_logic` + `one_shot` 格式，DeepSeek 实测正确生成多触发
  - 服务升级: create/update_automation 支持 triggers/trigger_logic/one_shot（schema 放宽）; get_automations 返回新字段 + records
  - 前端: 自动化卡片显示多触发（AND=& / OR=| 分隔）+ ONCE 徽标 + 🔧 按钮; add/edit sheet 动态 trigger 行 + 逻辑选择 + one-shot 开关; 新 `autoDebugSheet` 显示该自动化的触发配置 + 执行记录（成功/失败 + 时间 + 结果）
  - dev 环境: 新增 7 个 input_boolean + 3 个 input_number + 3 个 template sensor（烟雾/CO2/窗户开度），dashboard 增加"传感器(新)/环境"卡片与自动化调试板块
  - 测试覆盖: OR one-shot 自毁 ✓、AND 条件全满足才触发 ✓、时间触发准时+每日重复 ✓、执行记录持久化 ✓、旧格式兼容 ✓、LLM 端到端多触发创建 ✓、复合表达式 `(0 and 1) or 2` 三分支触发 ✓、UI 全流程（创建/编辑/调试弹窗/一次性自毁）✓

### Task 7b: 自动化完整回归测试 + 缺陷修复（2026-08-01）
- **类型**: fix | **产物**: `docs/dev/AUTOMATION_TEST_PLAN.md`（用例计划）、`docs/dev/TEST_REPORT.md`（报告）、`.pi/skills/llm-test/automation_test_suite.py`（可执行套件）
- **覆盖**: 72 用例全过（A 创建 14 / B 触发 15 / C 一次性 5 / D 管理 14 / E LLM 创建 7 / F 持久化 5 / G UI 12）
- **修复的产品 Bug（3）**:
  1. 纯 time 触发永不触发——`_evaluate_all_entity_triggers` 对 time-only 自动化返回 False（time trigger 在 `_trigger_satisfied` 恒 False）；修复：无 entity trigger 时直接返回 True
  2. LLM "一分钟后"生成过去时间（忽略秒）→ 定时排到明天；修复：HARDCODED prompt 强调相对时间必须严格晚于当前 Time
  3. LLM 幻觉"自动化已存在"（据 `sensor.llm_last_input` 推断）拒绝创建；修复：prompt 明确"用户要求创建时必须输出 create_automation，系统不查重"
- **修复的 UI 缺陷（3）**:
  4. `collectTriggers` 不处理 time 行 → 编辑 time 自动化崩溃；修复：time 行检测分支
  5. 添加表单无 time 触发器入口；修复：`addTimeTriggerRow()` + "⏰ 添加定时触发"按钮（add/edit）
  6. `alert()` 在 sandbox iframe 被忽略（allow-modals 未设置）→ 校验/错误提示不可见；修复：全部改用 `showToast()`，校验失败不关闭表单
- **测试工具**: `automation_test_suite.py` 支持 `python3 ... A,B,C` 分组运行；WS auth 不带 id（HA 2026.7）；reset 用 stop→清空→start（防 shutdown 写回）
- **状态**: ✅ 已完成（并入 v1.9.0，PR #24）

### Task 7c: 定时计划扩展——完整时间 + 周期性任务（2026-08-01）
- **类型**: feat | **分支**: `feat/schedule-time-triggers`（并入 v1.9.0，PR #24）
- **功能**: time trigger 支持 `schedule`（once/daily/weekly/monthly）：
  - **once**（一次性）：`datetime` 字段 "YYYY-MM-DDTHH:MM[:SS]"（年月日时分秒），触发后不再重复；无 schedule 但带 datetime 时自动推断为 once
  - **daily**（每天）：`time` HH:MM，默认行为（向后兼容）
  - **weekly**（每周）：`time` + `weekdays` [1=周一..7=周日]，多选（[1,3,5] = 每周一三五）
  - **monthly**（每月）：`time` + `days_of_month` [1..31]，多选（[1,15] = 每月1号和15号）；无效日期（如31号在短月）自动顺延跳过
- **实现**: `_compute_next_fire(trigger, now)` 计算下一次触发（weekly 扫描 7 天 / monthly 扫描 62 天边界）；`_register_time_trigger` 触发后按 schedule 重注册；无未来时间则停止（"schedule complete"）
- **LLM prompt**: HARDCODED 增加 4 种 schedule 示例（"每个星期一早上8点"→weekly weekdays:[1] 等），DeepSeek 实测正确生成 weekly/monthly/daily
- **UI**: 定时行加 schedule 选择器（一次性/每天/每周/每月）；每周显示 7 个星期 chips（一~日）；每月显示日期添加器（1-31 + chips）；一次性显示 datetime-local 原生选择器；卡片显示 "每周一 08:00" / "每月1号 09:00" / "每天 23:00" / 具体时间
- **秒级精度**: time/datetime 输入加 `step=1`（原生控件支持秒选择）；`_compute_next_fire` 解析 `time` 的 "HH:MM:SS" 或独立 `second` 字段（0-59 校验）；once 的 datetime 支持秒；秒为 00 时自动裁剪（"23:00" 而非 "23:00:00"）；LLM prompt 注明仅用户要求精确秒时才输出秒；端到端验证 13:55:10.000 秒级触发 ✓
- **UI 精修 v5**: 实体自动补全下拉独立层级（z-index 90 + blur(24px) + 双层阴影 + 选项"选择"提示 + 点击后立即隐藏）；原生 time/datetime 输入 `color-scheme: light dark`（暗黑主题原生 picker 跟随）；一次性标签改软胶囊 pill（10px / font-weight 400 / rounded-full / 琥珀色 bg 10% + text + border 30%）
- **UI 精修 v8（多条件 Sheet 布局）**: 纯 CSS/JS 视觉层，零功能改动；
  1. time/datetime 输入强制 `color-scheme: dark` + `appearance: none`（原生 picker 契合暗色、去除移动端默认外边框挤压）
  2. 触发卡片内部全部改 grid：头部 `auto 1fr auto`（序号/类型切换/删除）、设备字段 `minmax(0,1fr) 96px`（条件框固定 96px 不再挤压）、sched 顶行 `auto 1fr`、星期 chips `repeat(7, 1fr)` 七列等宽（实测 56px×7）、月日行 `80px auto 1fr`
  3. 自动补全下拉 z-index 90→120 + 阴影加深（0 20px 48px + 0 6px 16px）浮在所有卡片与按钮之上
  4. 添加触发条件按钮改极简虚线（1px dashed + 透明底 + hover 蓝色边框）；标签统一 12px
  5. 修 2 处行内 `style.display='flex'` 覆盖 grid（syncSchedDisplay 星期行、setRowType 设备字段）→ 改 'grid'；i18n-audit allowlist 加 'grid'
- **定时提醒（Task 7d）**: "1分钟后提醒我出门" 等提醒类请求 → once one-shot 自动化 + 触发时 LLM TTS 播报（"时间到了，该出门了！"）；增强：
  1. LLM 偶发把 `one_shot` 放进 trigger 内 → 创建时提升到自动化顶层
  2. LLM 输出 `time+schedule:once`（无 datetime）→ 按最近 HH:MM 触发一次（容错），once 永不重注册
  3. ReAct 循环重复 create → 后端去重（同 triggers+prompt+description 复用已有 id，实测 8 个→1 个）
  4. 提醒兜底：LLM 无动作且无 TTS 时把 prompt 作为提醒播报（`_clean_reminder_text` 净化"提醒我"前缀）
  5. prompt 注明"每次请求只创建一次，创建后确认不重复创建"
- **修复**: `async_create_automation` 触发器过滤遗漏 `datetime` 字段（once 创建被拒）；`triggerLabel(t)` 参数名遮蔽全局 i18n `t()`（time 分支报错）
- **测试**: `_compute_next_fire` 单元测试 14 场景全过（daily 今天/明天、weekly 周几+今天、monthly 跨月+31号短月、once 未来/已过/今天）；once 端到端触发（13:43 准时 + schedule complete）；LLM 创建三种周期自动化 ✓；UI 表单各 schedule 模式 + 编辑回填 ✓；回归 29/29 ✓

---

## ⚙️ 配置与多实例

### Task 8: 配置项改进
- **类型**: feat | **分支**: `feat/config-improvements`
- **包含**:
  - [x] 历史阶段模式的单选器改成两个独立开关（count / time 可都开、单开、都关）
  - [x] 配置多个中枢可在 AI Chat 切换（已支持），但各中枢的 LLM sensor 不能共用（要按实例区分）
  - [x] 设置里可关闭 AI Chat 侧边栏显示（默认开）
- **分析**: 历史开关改动小但涉及配置迁移；多实例 sensor 需要用 entry_id 区分 entity_id（如 `sensor.llm_last_response_<实例名>`）+ options flow 加 panel 开关
- **状态**: ✅ 已完成（v1.5.0，PR #20）

### Task 9: 实体别名传给模型
- **现象**: 用户配置的实体 alias 也要传给模型
- **类型**: chore | **分支**: `chore/entity-alias-to-prompt`
- **分析**: 读 HA entity registry 的 `aliases` 字段加进 exposed_entities CSV，小改动，可单独快速做掉
- **状态**: ✅ 已完成（v1.3.4）
- **实现方案**: 在 `_build_exposed_entities_list()` 和 `_build_entity_csv()` 中通过 `self.hass.data.get("entity_registry")` 获取 EntityRegistry 实例，对每个实体调用 `registry.async_get(entity_id)` 读取 `entry.aliases`（字符串列表）；过滤掉 HA 内部 `ComputedNameType` 枚举值，只保留用户配置的字符串别名；在聊天 prompt 的实体名后追加 `[别名1, 别名2]`，在自动化 CSV 中追加 `aliases` 列

---

## 📋 建议实施顺序

> 已完成：Task 1（v1.2.2）、Task 2（v1.2.3）、Task 2b（v1.2.4）、Task 9（v1.3.4）、Task 3（v1.3.0/1.3.1）、Task 4a（v1.3.3）、Task 5（v1.4.0/1.4.1）、Task 8（v1.5.0）、Task 6（v1.6.0）、Task 7（v1.7.0）、Task 4b（v1.8.0）、Task 7b/7c（v1.9.0）、UI v8（v1.10.0）、HACS 图标（v1.10.1）

> 🎉 **全部 roadmap 任务已完成**，不再有剩余开放任务。后续需求以新 issue / 新 roadmap 形式提出。

### 额外修复：HACS 商店图标缺失（brand/）
- **现象**: HACS 商店里显示 "icon not available"——根目录缺 `brand/icon.png`
- **原因**: HA 品牌 API 用 `custom_components/llm_smart_assistant/brand/`，而 HACS 商店从**仓库根目录** `brand/icon.png` 读图；根目录从未建过 brand 目录
- **修复**: 从 integration 内 512px PNG 缩放生成根目录 `brand/icon.png`（128×128）+ `icon@2x.png`（256）+ `logo.png`（256）+ `logo@2x.png`（512）
- **状态**: ✅ 完成（v1.10.1，PR #26）

| 顺序 | Task | 理由 |
|------|------|------|
| — | 全部任务已完成 | — |
