---
name: llm-test
description: |
  LLM Smart Assistant 测试与调试工作流。包括虚拟设备管理、dashboard 配置、
  测试用例编写与执行、结果分析。
---

# LLM Smart Assistant 测试指南

## 环境

- Dev HA: `http://localhost:8123`（Docker）
- 凭证: `agent` / `password`
- Token 位置: `.user/credentials.json` 的 `ha_token` 字段（相对项目根目录，gitignored）
- 日志: `config/home-assistant.log`（相对项目根目录）
- 存储: `config/.storage/llm_smart_assistant.storage_{entry_id}`（per-instance，相对项目根目录）
- 配置: `configuration.yaml` 中的虚拟设备

## 初始化

```bash
# 获取 token（长期令牌，存放在 .user/credentials.json 的 ha_token 字段，由 dev-setup 创建）
# 详见 ha-api skill 的 Authentication 章节
TOKEN=$(python3 -c "import json;print(json.load(open('.user/credentials.json'))['ha_token'])")

# 清空对话历史（每次测试前建议清理；storage 是 per-instance，替换 <entry_id>）
python3 << 'PYEOF'
import json
path = 'config/.storage/llm_smart_assistant.storage_<entry_id>'
d = json.load(open(path))
d['data']['history'] = []
d['data']['automations'] = []
json.dump(d, open(path, 'w'), ensure_ascii=False, indent=2)
PYEOF

# 重启 HA（修改 .py 文件后需要）
docker compose restart
# 等待就绪
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code}" http://localhost:8123/ 2>/dev/null | grep -q "200\|302" && break
  sleep 2
done
```

---

## 1️⃣ 虚拟设备管理

设备定义在 `configuration.yaml` 中：

```yaml
# ── 开关类（input_boolean）──
# turn_on / turn_off / toggle
input_boolean:
  living_room_light:    # 客厅灯
  bed_room_light:       # 卧室灯
  kitchen_light:        # 厨房灯
  study_light:          # 书房灯
  porch_light:          # 门廊灯
  tv:                   # 电视
  air_conditioner:      # 客厅空调
  bed_room_ac:          # 卧室空调
  water_heater:         # 热水器
  garage_door:          # 车库门
  front_door_lock:      # 大门锁
  alarm_system:         # 安防系统
  robot_vacuum:         # 扫地机器人

# ── 数值类（input_number）──
# set_value 或 set_value with "value"
input_number:
  test_temperature:     # 客厅温度(°C) -10~50
  target_temperature:   # 空调目标温度(°C) 16~30
  fan_speed:            # 风扇转速(%) 0~100
  volume_level:         # 音量(%) 0~100
  outdoor_temp:         # 室外温度模拟(°C) -10~50
  curtain_position:     # 窗帘开度(%) 0~100

# ── 选项类（input_select）──
# select_option with "option"
input_select:
  hvac_mode:            # off/cool/heat/dry/fan_only
  fan_mode:             # auto/low/medium/high
  ac_swing:             # off/vertical/horizontal/both

# ── 模板传感器（template sensor）──
template:
  - sensor:
      - name: "Test Voice Input"        # 语音输入触发器（通过设置state触发LLM）
      - name: "客厅温度"                 # 读取 input_number.test_temperature
      - name: "室外温度"                 # 读取 input_number.outdoor_temp
      - name: "室内湿度"                 # 随机 45~65%
```

### 虚拟扬声器（TTS 多设备路由测试）

> 本地 dev 集成（**不提交仓库**，已在 .gitignore）：`custom_components/virtual_speakers/`，在 `configuration.yaml` 用 `media_player: - platform: virtual_speakers` 加载。

生成 3 个 media_player：

| entity_id | 名称 | 建议区域 |
|-----------|------|---------|
| `media_player.ke_ting_yin_xiang` | 客厅音箱 | 客厅 (`ke_ting`) |
| `media_player.wo_shi_yin_xiang` | 卧室音箱 | 卧室 (`wo_shi`) |
| `media_player.chu_fang_yin_xiang` | 厨房音箱 | 厨房 (`chu_fang`) |

每个实体接受 `play_media`（记录 `spoken_text` 属性，2 秒后回 idle），用于验证 Task 4b 多设备 TTS 路由：

```bash
# 给实体分配区域（WS API，id 必须递增）
# config/entity_registry/update, entity_id=media_player.wo_shi_yin_xiang, area_id=wo_shi

# 带来源设备调用（LLM 应选择同区域音箱）
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/process_input" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "现在几点了", "source_entity": "sensor.test_voice_input", "entry_id": "<entry_id>"}'

# 检查 TTS 落点
docker logs hass-dev --since 60s 2>&1 | grep "TTS spoken"
```

### 设备控制 API

```bash
# 开关类
curl -s -X POST "http://localhost:8123/api/services/input_boolean/turn_on" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "input_boolean.kitchen_light"}'

# 数值类
curl -s -X POST "http://localhost:8123/api/services/input_number/set_value" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "input_number.target_temperature", "value": 26}'

# 选项类
curl -s -X POST "http://localhost:8123/api/services/input_select/select_option" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "input_select.hvac_mode", "option": "cool"}'
```

### 设备完整列表

可以在浏览器打开 `http://localhost:8123/llm-devices` 查看全部虚拟设备的状态。

---

## 1.5️⃣ 自动化完整测试套件

> 用例计划: `docs/dev/AUTOMATION_TEST_PLAN.md` | 报告: `docs/dev/TEST_REPORT.md`

```bash
# 分组运行（A 创建 / B 触发 / C 一次性 / D 管理 / E LLM 创建 / F 持久化）
python3 .pi/skills/llm-test/automation_test_suite.py A,B,C,D
python3 .pi/skills/llm-test/automation_test_suite.py E    # 含 stop→清空→start 重置，~5 分钟
python3 .pi/skills/llm-test/automation_test_suite.py F    # 含重启，~1 分钟

# 全部
python3 .pi/skills/llm-test/automation_test_suite.py A,B,C,D,E,F
```

要点：
- **E 组前必须清空 history**（LLM 会记住之前的"创建自动化"请求并拒绝重复——脚本内自动处理）
- 清空 storage 用 `docker compose stop → 改文件 → start`，不能用 restart（coordinator shutdown 会把内存 history 写回）
- WS auth 消息不带 `id` 字段（HA 2026.7 要求）
- UI 层（G 组）用 Playwright 手测：`/llm-chat` → 自动化 tab → 添加/编辑/删除/🔧 debug/开关

### 定时计划（schedule）测试要点

time trigger 支持 4 种 schedule（Task 7c，v1.8.1）：

| schedule | 字段 | 示例 |
|----------|------|------|
| once（一次性） | `datetime` "YYYY-MM-DDTHH:MM" | `{"type":"time","datetime":"2026-08-15T13:30"}` |
| daily（每天） | `time` "HH:MM" | `{"type":"time","time":"23:00"}`（默认） |
| weekly（每周） | `time` + `weekdays` [1=周一..7=周日] | `{"time":"08:00","schedule":"weekly","weekdays":[1]}` |
| monthly（每月） | `time` + `days_of_month` [1..31] | `{"time":"09:00","schedule":"monthly","days_of_month":[1]}` |

- LLM 自然语言："每个星期一早上8点启动扫地机器人" → weekly；"每月1号上午9点打开车库门" → monthly；"每天晚上11点关闭空调" → daily
- once 已过时间不注册（日志 `no future occurrence`）；once 触发后不重复（`no next occurrence, schedule complete`）
- **秒级精度**：`time` 支持 "HH:MM:SS" 或独立 `second` 字段；`datetime` 支持秒；UI 输入 `step=1` 可选秒；秒为 00 自动裁剪
- **定时提醒**："1分钟后提醒我出门" → once one-shot + 触发时 TTS 播报；LLM 可能把 `one_shot` 放 trigger 内（自动提升顶层）、生成 `time+schedule:once` 无 datetime（按最近 HH:MM 触发一次）、ReAct 循环重复 create（后端去重）
- monthly 31 号在短月自动顺延跳过（扫描 62 天）
- 前端表单：定时行 schedule 选择器 + 星期 chips + 日期添加器 + datetime-local

---

## 2️⃣ Dashboard

路径: `http://localhost:8123/llm-devices`

布局（从上到下竖向堆叠，适配竖屏）:

| 区块 | 内容 |
|------|------|
| 💡 灯光 | 5个灯的开关 |
| ❄️ 空调 | 2个空调 + 模式/风速/摆风 + 目标温度/风扇转速 |
| 🌡️ 传感器 | 客厅/室外温度、湿度、调节滑块 |
| 🔒 安防 | 大门锁、安防系统、车库门 |
| 🎮 其他 | 电视、热水器、扫地机、窗帘、音量 |
| 🧪 调试 | 语音输入（显示最后输入）、LLM 回复、LLM 调试数据 |

### 创建 / 更新 Dashboard

新 dev 环境初始化时**必须**运行（幂等，可重复执行）：

```bash
pip install websockets   # 如未安装
python3 .pi/skills/llm-test/setup_dashboard.py
```

脚本通过 WebSocket API 创建 `/llm-devices` 面板并写入完整布局。
修改布局请直接编辑 `setup_dashboard.py` 中的 `DASHBOARD_CONFIG` 后重跑。

---

## 3️⃣ 测试流程

### 方式 A：通过传感器触发（推荐，dashboard 可见输入内容）

```bash
# 1. 通过 sensor.test_voice_input 发送指令
# （dashboard 上会显示输入内容）
curl -s -X POST "http://localhost:8123/api/states/sensor.test_voice_input" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"state": "打开厨房灯", "attributes": {"friendly_name": "Test Voice Input"}}'

# 2. 等待 LLM 处理（每轮约 2-5 秒）
sleep 12

# 3. 查看结果
curl -s "http://localhost:8123/api/states/sensor.llm_last_response" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 4. 验证设备状态
curl -s "http://localhost:8123/api/states/input_boolean.kitchen_light" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin).get('state'))"
```

### 方式 B：通过 AI Chat 面板（最直观）

打开 `http://localhost:8123/llm-chat`，直接在聊天框输入。

### 方式 C：通过 process_input 服务（无 UI 显示）

```bash
# 适合自动化测试脚本
curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/process_input" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "关闭客厅灯"}'
```

---

## 4️⃣ 测试用例

### 基础操作

```bash
test_simple() {
  local input="$1" desc="$2" entity="$3" expect="$4"
  echo "▶ $desc"
  
  # 重置
  curl -s -X POST "http://localhost:8123/api/services/llm_smart_assistant/process_input" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"text\":\"$input\"}" > /dev/null
  
  sleep 8
  
  # 检查状态
  state=$(curl -s "http://localhost:8123/api/states/$entity" \
    -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin).get('state','?'))")
  
  if [ "$state" = "$expect" ]; then
    echo "  ✅ $state"
  else
    echo "  ❌ 期望=$expect 实际=$state"
  fi
}
```

### 测试场景

| # | 场景 | 输入 | 预期行为 | 检查项 |
|---|------|------|---------|--------|
| 1 | 开灯 | `打开厨房灯` | input_boolean.turn_on | kitchen_light → on |
| 2 | 关灯 | `关闭客厅灯` | input_boolean.turn_off | living_room_light → off |
| 3 | 多设备 | `关闭厨房灯并打开门廊灯` | 两个 call_service | kitchen_light→off, porch_light→on |
| 4 | 查传感器 | `现在几度` | get_states 返回温度 | tts_text 含温度值 |
| 5 | 设温度 | `空调调到26度` | input_number.set_value target=26 | target_temperature → 26.0 |
| 6 | 设模式 | `空调设成制热` | input_select.select_option hvac_mode=heat | hvac_mode → heat |
| 7 | 调风扇 | `风扇设成低速` | input_select.select_option fan_mode=low | fan_mode → low |
| 8 | 安防 | `打开大门锁` | input_boolean.turn_on | front_door_lock → on |
| 9 | 批量 | `关闭所有灯` | 多个 turn_off | 所有灯 → off |
| 10 | 条件 | `客厅灯开着吗` | get_states 查询 | tts_text 反映实际状态 |

---

## 5️⃣ 结果查看

### 方式 1：Dashboard

`http://localhost:8123/llm-devices` → 查看「🧪 调试」区块

| 实体 | 显示内容 |
|------|---------|
| `sensor.test_voice_input` | 最后输入的文本 |
| `sensor.llm_last_response` | LLM 最后回复的 tts_text |
| `sensor.llm_debug_raw` | 完整调试 JSON（含各轮对话） |

### 方式 2：HA 日志

```bash
# 查看 LLM 原始响应
grep "LLM raw response" config/home-assistant.log | tail -5

# 查看解析后的 JSON
grep "LLM JSON parsed" config/home-assistant.log | tail -5

# 查看推理轮次
grep "Reasoning round\|completed" config/home-assistant.log | tail -10

# 查看步骤执行
grep "Step execution\|Executed service" config/home-assistant.log | tail -10
```

### 方式 3：API 查询

```bash
# 完整响应
curl -s "http://localhost:8123/api/states/sensor.llm_last_response" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'TTS: {d.get(\"state\",\"\")}')
fr = d.get('attributes', {}).get('full_response', '{}')
try:
    p = json.loads(fr)
    print(f'Rounds: {p.get(\"iterations\",0)}')
    for r in p.get('rounds',[]):
        print(f'  tts=\"{r.get(\"tts_text\",\"\")}\"')
        for s in r.get('steps',[]):
            print(f'    {json.dumps(s, ensure_ascii=False)[:200]}')
except: pass
"
```

---

## 6️⃣ 常见问题

### LLM 返回空白（6-10 个空格）

DeepSeek 在 `response_format: json_object` 模式下约 20% 概率返回空白。
代码有重试机制（最多 3 次），通常能自动恢复。

### 实体被限制

检查 `const.py` 中 `RESTRICTED_DOMAINS` / `RESTRICTED_SERVICES` 列表，以及配置中的
domain/entity 白名单（`domains_whitelist`、`entities_whitelist`）。测试用的
`input_number`、`input_select`、`input_boolean` 默认不受限；若动作被拦截，日志中会
出现 `Step intercepted` 警告，说明被白名单拦截。

### 对话历史干扰

每次测试前清理 history：
```python
import json
# storage 是 per-instance，替换 <entry_id>
entry_id = '<entry_id>'
d = json.load(open(f'config/.storage/llm_smart_assistant.storage_{entry_id}'))
d['data']['history'] = []
json.dump(d, open(f'config/.storage/llm_smart_assistant.storage_{entry_id}', 'w'), ensure_ascii=False, indent=2)
```

### Prompt 修改后不生效

Python 文件修改后需要重启 HA：
```bash
docker compose restart
```

### Debug 查看完整 Prompt

```bash
curl -s "http://localhost:8123/api/states/sensor.llm_debug_raw" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('attributes', {}).get('prompt', 'No prompt')[:2000])
"
```
