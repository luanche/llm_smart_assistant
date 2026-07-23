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
  - [ ] 4b: 允许配置多个输入设备和输出设备提供给模型；用户用某设备输入时，由模型根据设备位置决定最合适的输出设备
- **分析**: 输入来源标记（`chat_ui` / `service_call` / 具体 sensor entity_id）决定默认是否 TTS；多输出设备需要配置结构改为列表 + prompt 中注入设备位置信息（area），模型在响应 JSON 中指定 `output_device`。建议拆两步：先 4a（chat 不 TTS），再 4b（多设备路由）
- **4a 实现方案**（`fix/chat-tts-browser`，v1.3.3）:
  1. **后端** `coordinator.py`: `entity_id` 为 "service_call" 或 "chat_ui" 时无条件跳过 `_async_speak_tts`（之前版本只对 text 跳过、voice 保留，现改为两者都跳过）
  2. **前端** `panel/index.html`: `sendMessage` 的 `handleState` 回调中，当 `fromVoice=true` 且收到 TTS 文本时，调用 `window.speechSynthesis.speak()` 通过浏览器播报，语音设为当前界面语言
- **状态**: ◀️ 4a 已完成（v1.3.3）

---

## 📱 AI Chat 移动端 UI

### Task 5: 移动端可用性优化
- **类型**: feat | **分支**: `feat/mobile-ui-polish`
- **包含**:
  - [ ] 顶部"聊天/自动化"tab 按钮太小，手机端整体字体/按钮偏小
  - [ ] 提供复制 AI Chat 页面链接的地方（方便单独用浏览器打开）
  - [ ] 聊天窗口左右滑切换聊天/自动化页面（注意不要和 HA 侧边栏手势冲突）
- **分析**: 整体过一遍 touch target（≥44px）和字号；滑动手势在内容区域做、加边缘 dead zone（左侧 ~20px 不响应）避免与 HA 侧边栏冲突
- **状态**: ⬜ 未开始

---

## 💬 聊天历史

### Task 6: 历史聊天记录显示
- **类型**: feat | **分支**: `feat/chat-history-panel`
- **包含**:
  - [ ] 生成的实体除了 LLM Last Response，也记录最后一次输入内容
  - [ ] AI Chat 显示历史聊天记录——用 HA recorder 的 sensor 历史（不要缓存），多个输入设备 + AI Chat 的记录都显示，懒加载分页
- **分析**: 第 1 点是第 2 点的基础（先做）；历史数据源用 HA recorder 的 `history/period` API 读 `sensor.llm_last_response` + 输入 sensor 的状态变化，按时间线合并；懒加载用时间游标向上翻页
- **依赖**: Task 8（多实例 sensor 独立，才能区分不同中枢的历史）
- **状态**: ⬜ 未开始

---

## ⚡ 自动化引擎增强

### Task 7: 自动化能力升级（核心，改动最大）
- **类型**: feat | **分支**: `feat/automation-engine-v2`
- **包含**:
  - [ ] 一条自动化允许配置多个传感器，条件用逻辑运算符连接（AND/OR）；且不只 sensor，开关等实体、当前时间等也可作为监听源
  - [ ] 自动化分一次性/长期，由模型根据用户输入决定（如"1分钟后关闭空调"=临时）
  - [ ] Automation 的执行也要记录，方便回溯 debug
  - [ ] AI Chat Automation 界面点 debug 按钮，显示该 automation 的 debug 信息而不是 chat 的
- **分析**: 触发模型从"单实体+条件"升级为"多触发源+逻辑表达式"；一次性自动化用 `async_track_point_in_time` 或触发后自毁；执行记录存 storage（环形缓冲，保留最近 N 条），debug 弹窗按来源显示。建议拆 2 个 PR：先多触发源，再一次性功能+执行记录
- **状态**: ⬜ 未开始

---

## ⚙️ 配置与多实例

### Task 8: 配置项改进
- **类型**: feat | **分支**: `feat/config-improvements`
- **包含**:
  - [ ] 历史阶段模式的单选器改成两个独立开关（count / time 可都开、单开、都关）
  - [ ] 配置多个中枢可在 AI Chat 切换（已支持），但各中枢的 LLM sensor 不能共用（要按实例区分）
  - [ ] 设置里可关闭 AI Chat 侧边栏显示（默认开）
- **分析**: 历史开关改动小但涉及配置迁移；多实例 sensor 需要用 entry_id 区分 entity_id（如 `sensor.llm_last_response_<实例名>`）+ options flow 加 panel 开关
- **状态**: ⬜ 未开始

### Task 9: 实体别名传给模型
- **现象**: 用户配置的实体 alias 也要传给模型
- **类型**: chore | **分支**: `chore/entity-alias-to-prompt`
- **分析**: 读 HA entity registry 的 `aliases` 字段加进 exposed_entities CSV，小改动，可单独快速做掉
- **状态**: ✅ 已完成（v1.3.4）
- **实现方案**: 在 `_build_exposed_entities_list()` 和 `_build_entity_csv()` 中通过 `self.hass.data.get("entity_registry")` 获取 EntityRegistry 实例，对每个实体调用 `registry.async_get(entity_id)` 读取 `entry.aliases`（字符串列表）；过滤掉 HA 内部 `ComputedNameType` 枚举值，只保留用户配置的字符串别名；在聊天 prompt 的实体名后追加 `[别名1, 别名2]`，在自动化 CSV 中追加 `aliases` 列

---

## 📋 建议实施顺序

| 顺序 | Task | 理由 |
|------|------|------|
| 1 | Task 1（重启重复执行）| 高危 bug |
| 2 | Task 2（release changelog）| pipeline bug，影响每次发版 |
| 3 | Task 9（实体 alias）| 小改动，快速收益 |
| 4 | Task 4a（chat 不 TTS）| 小改动，体验影响大 |
| 5 | Task 3（PTT 语音交互）| 语音体验核心 |
| 6 | Task 5（移动端 UI）| 独立性高 |
| 7 | Task 8（配置/多实例）| Task 6 的前置 |
| 8 | Task 6（聊天历史）| 依赖 Task 8 |
| 9 | Task 7（自动化引擎 v2）| 最大改动，放后面 |
| 10 | Task 4b（多设备路由）| 依赖架构成熟后做 |
