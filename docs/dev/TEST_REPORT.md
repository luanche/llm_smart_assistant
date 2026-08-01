# 动态自动化完整测试报告

> 测试日期: 2026-08-01 | 分支: master (v1.8.0) | 环境: Docker hass-dev (HA 2026.7.2)

## 测试概览

| 层级 | 用例数 | 通过 | 失败 | 通过率 |
|------|--------|------|------|--------|
| API 创建 (A) | 14 | 14 | 0 | 100% |
| API 执行触发 (B) | 15 | 15 | 0 | 100% |
| 一次性自动化 (C) | 5 | 5 | 0 | 100% |
| 管理操作 (D) | 14 | 14 | 0 | 100% |
| LLM 自然语言创建 (E) | 7 | 7 | 0 | 100% |
| 持久化 (F) | 5 | 5 | 0 | 100% |
| UI 交互 (G) | 12 | 12 | 0 | 100% |
| **合计** | **72** | **72** | **0** | **100%** |

## 发现并修复的问题

### 🔴 严重（产品 Bug，3 个）

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| 1 | **纯 time 触发自动化永不触发**：`_evaluate_all_entity_triggers` 对 time-only 自动化返回 False（`_trigger_satisfied` 对 time trigger 恒 False → `any()` 空 → False），导致 `_async_handle_time_trigger` 前置检查拦截 | "一分钟后打开电视"等定时自动化完全失效 | `_evaluate_all_entity_triggers` 增加特判：无 entity 触发器时直接返回 True（时间到即触发） |
| 2 | **LLM 创建"一分钟后"生成过去时间**：DeepSeek 忽略秒数，生成当前分钟（如 12:39:47 创建 → time=12:40 已在 13 秒后）或恰好在当前分钟 → `fire_at <= now` 顺延到**明天** | 相对时间请求排期错误，定时永不触发 | prompt 增加明确指令：相对时间必须严格晚于当前 Time（含秒），"一分钟后"= 当前时间 +1 分钟 |
| 3 | **LLM 幻觉"自动化已存在"**：DeepSeek 看到 `sensor.llm_last_input` 显示旧输入（如"创建自动化：当厨房灯打开时…"）即推断"该自动化已存在，无需重复创建"并跳过 create_automation | 用户重复创建/同 session 再次创建被拒绝 | prompt 增加指令：用户要求创建时**必须**输出 create_automation 动作，系统不查重 |

### 🟠 UI 缺陷（3 个）

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| 4 | **`collectTriggers` 不处理 time 行**：编辑含 time 触发器的自动化时，对 `.trig-time` 行执行 `row.querySelector('.trig-entity').value` → null 抛异常 | 编辑 time 自动化崩溃/静默失败 | `collectTriggers` 增加 time 行检测分支 |
| 5 | **添加表单无 time 触发器入口**：只能加实体行，time 触发器无法手动创建 | 功能缺口 | 添加"⏰ 添加定时触发"按钮 + `addTimeTriggerRow()`（add/edit 双表单），time 行带索引 span 支持表达式 |
| 6 | **`alert()` 在 sandbox iframe 被忽略**（`allow-modals` 未设置）：confirmAdd/confirmEdit 空触发器校验 alert 不显示，表单关闭但用户无反馈；其他 2 处 alert 同样失效 | 校验提示不可见 | 全部改用 `showToast()`（页面内 toast 机制）；校验失败时**不关闭表单** |

### 🟡 测试工具改进（2 个）

| # | 问题 | 修复 |
|---|------|------|
| 7 | `reset_history_and_restart` 用 `docker compose restart`：coordinator shutdown 时把内存 history（44 条）写回 storage，覆盖清空 | 改用 `stop → 清空 storage → start` |
| 8 | 测试脚本缺陷：D2b 场景设备已处于目标状态（无状态变化不触发）；B8 "仅0满足"场景因 bed 默认 off 不成立；E2b tv 初始 on 假阳性 | 修正场景设计（先制造状态变化；显式 set 目标 off）；E2a 新增"时间为未来"断言 |

## 测试用例详情

### A. 创建（14 项，全过）
- A1 单触发器 / A2 OR / A3 AND / A4 复合表达式 `(0 and 1) or 2` / A5 时间 / A6 one-shot
- 防御性：A7 空触发器不崩溃（后端 `no valid triggers`）、A8 非法逻辑回退 or

### B. 执行触发（15 项，全过）
- B1/B2 单触发器命中/不命中、B3 OR、B4/B5 AND 全满足/缺一、B6/B7/B8 表达式三场景（(0and1)、仅2、仅0）、B9/B10 数值条件

### C. 一次性（5 项，全过）
- C1 触发执行、C1b 自毁（API 列表）、C2 存储无残留、C3 未触发不删除

### D. 管理（14 项，全过）
- D1 查询、D2 更新条件生效、D4 更新触发器重注册（旧失效新生效）、D5/D6 删除/不存在、D7/D8 禁用/启用、D9 执行记录字段

### E. LLM 创建（7 项，全过）
- E1 聊天创建实体自动化、E3 复合条件、E4 触发执行、E2/E2a/E2b/E2c 定时创建+未来时间+触发+自毁

### F. 持久化（5 项，全过）
- F1 重启保留、F1b 重启后存在、F2 重启后触发有效、F3 记录保留

### G. UI 交互（12 项，全过）
- G1 空状态提示、G2 添加单触发器卡片、G3 三触发器+表达式 `(0 and 1) or 2` 徽章渲染 `(A==on AND B==off) OR C==on`、G4 AND/OR 切换（`&` 徽章）、G5 一次性徽章、G6 定时行添加+混合保存、G7 编辑回填（实体+time 行）、G8 删除确认+消失+不再触发、G9 debug 弹窗（Trigger/Logic/Action/执行记录）、G10 禁用不触发+启用恢复、G11 空触发器 toast 校验+表单不关闭、G12 表达式触发验证

## 遗留观察（非阻塞）

- `docker compose restart` 时 coordinator 会写回 storage（shutdown save）——测试清空需用 stop/start；日常无影响
- DeepSeek `json_object` 模式约 20% 返回空白（重试机制已兜底，E 组通过 chat_retry 验证）

## 回归确认

- A-D 组重跑 29/29 通过（修复后）
- Python/JS/i18n 全部检查通过
- `alert()` 残留 0 处（全部转 toast）
