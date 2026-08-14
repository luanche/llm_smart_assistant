# 动态自动化完整测试计划

> 针对 Task 7（自动化升级，v1.7.0）的完整回归测试。覆盖：创建（API/LLM）、执行触发、
> 一次性自毁、定时触发、复合表达式、管理操作、持久化、UI 交互。

## 测试环境

- HA: `http://localhost:8123`（Docker `hass-dev`）
- 存储: `config/.storage/llm_smart_assistant.storage_{entry_id}`（per-instance）
- 虚拟设备: `input_boolean.*` / `input_number.*` / `input_select.*` / template sensors
- 集成 entry_id: `GET /api/config/config_entries/entry/llm_smart_assistant` 获取（或看 `.storage/` 下文件名后缀）
- 测试前: 清空 `automations`（存储 JSON 的 `data.automations = []`）+ 重启

## 测试工具

- API 测试: `python3 .pi/skills/llm-test/automation_test_suite.py`（REST + WS）
- UI 测试: Playwright MCP 浏览器（`http://localhost:8123/llm-chat` → 自动化 tab）
- 日志: `docker logs hass-dev`（`LLM JSON parsed` / `Automation ... triggered` / `One-shot ... removing`）

## 用例清单

### A. 创建（API create_automation 服务）

| ID | 场景 | 输入 | 预期 |
|----|------|------|------|
| A1 | 单触发器 | `entity_id+condition`（legacy 格式） | 返回 UUID，get 可查，storage 持久化 |
| A2 | 多触发器 OR | 2 triggers + `trigger_logic=or` | 创建成功，卡片显示 OR |
| A3 | 多触发器 AND | 2 triggers + `trigger_logic=and` | 创建成功，卡片显示 AND |
| A4 | 复合表达式 | 3 triggers + `expression="(0 and 1) or 2"` | 创建成功，表达式原样存储 |
| A5 | 时间触发器 | `[{"type":"time","time":"HH:MM"}]` | 创建成功 |
| A6 | one-shot 标记 | `one_shot=true` | 创建成功，one_shot 持久化 |
| A7 | 空触发器防御 | 无 entity_id/time | 返回 None，不崩溃 |
| A8 | 非法逻辑防御 | `trigger_logic="xor"` | 回退 `or`，不崩溃 |

### B. 执行触发

| ID | 场景 | 前置 | 操作 | 预期 |
|----|------|------|------|------|
| B1 | 单触发器命中 | A1 自动化 | 实体设为满足条件 | LLM 执行动作，目标实体变化 |
| B2 | 单触发器不命中 | A1 自动化 | 实体设为不满足 | 无动作 |
| B3 | OR 任一命中 | A2 | 触发第 1 个 | 动作执行 |
| B4 | AND 全命中 | A3 | 两个都满足 | 动作执行 |
| B5 | AND 缺一个 | A3 | 只满足 1 个 | 不触发 |
| B6 | 表达式 (0 and 1) or 2 | A4 | 0 和 1 满足（2 不满足） | 触发 |
| B7 | 表达式仅 2 命中 | A4 | 仅 2 满足 | 触发 |
| B8 | 表达式缺一半 | A4 | 仅 0 满足 | 不触发 |
| B9 | 数值条件 >30 | `input_number.test_temperature` | 设 35 | 触发 |
| B10 | 数值条件不满足 | 同上 | 设 20 | 不触发 |
| B11 | 时间触发 | A5 时间=当前+1min | 等待到点 | 触发 |
| B12 | 时间+实体 AND | 时间触发+实体条件 | 实体不满足时到点 | 不触发 |

### C. 一次性自动化

| ID | 场景 | 操作 | 预期 |
|----|------|------|------|
| C1 | 触发后自毁 | 触发 one-shot 自动化 | 动作执行 + 自动化从列表消失 |
| C2 | 自毁不残留 | C1 后 | storage 无该 automation_id |
| C3 | 未触发不删除 | one-shot 不触发 | 自动化保留 |

### D. 管理操作

| ID | 场景 | 操作 | 预期 |
|----|------|------|------|
| D1 | 查询列表 | get_automations | 返回全部自动化（含字段） |
| D2 | 更新条件 | update_automation 改 condition | 按新条件触发 |
| D3 | 更新表达式 | update_automation 改 expression | 按新表达式触发 |
| D4 | 更新触发器重注册 | update 改 entity_id | 新实体变化触发，旧实体变化不触发 |
| D5 | 删除 | remove_automation | 列表消失 |
| D6 | 删除不存在 | 随机 ID | 返回 false，不崩溃 |
| D7 | 禁用 | toggle disable | 实体变化不触发 |
| D8 | 启用 | toggle enable | 实体变化恢复触发 |
| D9 | 执行记录 | 触发后 debug 数据 | records 含 time/trigger/result/ok/steps |

### E. LLM 自然语言创建

| ID | 场景 | 输入 | 预期 |
|----|------|------|------|
| E1 | 实体自动化 | "当厨房灯打开时打开风扇" | create_automation 步骤 → 自动化创建 |
| E2 | 定时自动化 | "一分钟后打开电视" | time 触发 one-shot 自动化 |
| E3 | 复合条件 | "当(烟雾高 或 窗户开)时扫地" | expression 自动化 |
| E4 | 触发 E1 | 厨房灯 on | 动作执行（风扇 on） |
| E5 | E2 到点自毁 | 等待 1 分钟 | 电视 on + 自动化删除 |

### F. 持久化

| ID | 场景 | 操作 | 预期 |
|----|------|------|------|
| F1 | 重启保留 | 创建后重启 HA | 自动化仍存在 |
| F2 | 重启后触发 | 重启后实体变化 | 仍能触发执行 |
| F3 | 重启后记录保留 | 触发后重启 | records 仍在 |

### G. UI 交互（Playwright）

| ID | 场景 | 操作 | 预期 |
|----|------|------|------|
| G1 | 空状态 | 无自动化时打开 tab | 显示"暂无自动化"提示 |
| G2 | 添加-单触发器 | 表单填 1 行保存 | 卡片出现 |
| G3 | 添加-多触发器 | 添加 3 行 + 表达式 `(0 and 1) or 2` | 卡片显示表达式徽章 |
| G4 | AND/OR 切换 | 表单选 AND | 卡片显示 AND 徽章 |
| G5 | one-shot 勾选 | 勾选一次性 | 卡片显示 [一次性] 徽章 |
| G6 | 时间触发器行 | type 选 time | 行切换为时间输入 |
| G7 | 编辑回填 | 编辑已有 | 字段正确回填，保存生效 |
| G8 | 删除交互 | 删除按钮 | 确认后卡片消失 |
| G9 | 🔧 debug 弹窗 | 点卡片🔧 | 显示触发器配置 + 执行记录 |
| G10 | 禁用/启用 | 卡片开关 | 禁用后不触发，启用恢复 |
| G11 | 表单校验 | 空触发器行 | 提示/阻止保存 |
| G12 | 顶部 vs 卡片🔧 | 两者都在 | 顶部=LLM debug，卡片=自动化 debug |

## 执行顺序

1. 清空存储 + 重启 HA
2. `automation_test_suite.py` 跑 A–F 全部用例
3. Playwright 跑 G 用例（结合真实交互）
4. 汇总 → `docs/dev/TEST_REPORT.md`
5. 修复发现的问题 → 重跑回归

## 判定标准

- 每个用例 PASS/FAIL，FAIL 需附日志/截图证据
- 防御性用例（A7/A8/D6）必须不崩溃
- 触发用例以**目标实体实际状态变化**为准（不是仅看日志）
