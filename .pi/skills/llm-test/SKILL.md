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
- Token 位置: `/tmp/hass_token.txt`
- 日志: `config/home-assistant.log`（相对项目根目录）
- 存储: `config/.storage/llm_smart_assistant.storage`（相对项目根目录）
- 配置: `configuration.yaml` 中的虚拟设备

## 初始化

```bash
# 获取 token（使用 ha-api skill 中的 refresh_token 流程，缓存到 /tmp/hass_token.txt）
if [ ! -s /tmp/hass_token.txt ]; then
  curl -s -X POST http://localhost:8123/auth/token \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=refresh_token&refresh_token=<见 ha-api skill>&client_id=http://localhost:8123/" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])" > /tmp/hass_token.txt
fi
TOKEN=$(cat /tmp/hass_token.txt)

# 清空对话历史（每次测试前建议清理）
python3 << 'PYEOF'
import json
path = 'config/.storage/llm_smart_assistant.storage'
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

### 更新 Dashboard

```bash
# 通过 WebSocket API 更新
# 见下方示例脚本
```

<details>
<summary>完整更新脚本</summary>

```python
import asyncio, json, websockets

TOKEN = open("/tmp/hass_token.txt").read().strip()

async def update_dashboard():
    async with websockets.connect("ws://localhost:8123/api/websocket") as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        await ws.recv()
        
        config = {
            "title": "智能设备",
            "views": [{
                "title": "智能设备",
                "icon": "mdi:devices",
                "cards": [
                    {"type": "entities", "title": "💡 灯光", "show_header_toggle": True,
                     "entities": ["input_boolean.living_room_light", ...]},
                    # ... 更多卡片
                    {"type": "entities", "title": "🧪 调试", "entities": [
                        {"entity": "sensor.test_voice_input", "name": "语音输入"},
                        {"entity": "sensor.llm_last_response", "name": "LLM 回复"},
                        {"entity": "sensor.llm_debug_raw", "name": "调试数据"},
                    ]},
                ]
            }]
        }
        
        await ws.send(json.dumps({
            "id": 1, "type": "lovelace/config/save",
            "url_path": "llm-devices", "config": config
        }))
        await ws.recv()

asyncio.run(update_dashboard())
```
</details>

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
d = json.load(open('config/.storage/llm_smart_assistant.storage'))
d['data']['history'] = []
json.dump(d, open(..., 'w'), ensure_ascii=False, indent=2)
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
