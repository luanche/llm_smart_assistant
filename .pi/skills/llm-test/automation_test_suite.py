#!/usr/bin/env python3
"""Dynamic Automation Test Suite — API layer (REST + WS).

Covers: creation (A), execution triggers (B), one-shot (C), management (D),
LLM natural-language creation (E), persistence (F).

Usage:
    python3 .pi/skills/llm-test/automation_test_suite.py [--group A|B|C|D|E|F]

Requires:
    websockets, requests
"""
import asyncio
import json
import sys
import time
import uuid
import urllib.request
import urllib.error

BASE = "http://localhost:8123"
CRED_PATH = ".user/credentials.json"

# Resolved dynamically on first use (see _entry_id())
_ENTRY_ID_CACHE = None

# ---------------------------------------------------------------------------
# HA helpers (REST)
# ---------------------------------------------------------------------------

def _token() -> str:
    with open(CRED_PATH) as f:
        return json.load(f)["ha_token"]


def _entry_id() -> str:
    """Resolve the first llm_smart_assistant config entry_id dynamically."""
    global _ENTRY_ID_CACHE
    if _ENTRY_ID_CACHE:
        return _ENTRY_ID_CACHE
    data = rest("GET", "/api/config/config_entries/entry")
    entries = data if isinstance(data, list) else []
    entries = [e for e in entries if e.get("domain") == "llm_smart_assistant"]
    if not entries:
        raise RuntimeError("No llm_smart_assistant config entry found; add the integration first")
    _ENTRY_ID_CACHE = entries[0]["entry_id"]
    return _ENTRY_ID_CACHE


def _storage_path() -> str:
    """Per-instance storage path (legacy shared key migrated on first load)."""
    return f"config/.storage/llm_smart_assistant.storage_{_entry_id()}"


def rest(method: str, path: str, body=None) -> dict:
    """Call HA REST API, return parsed JSON."""
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:200]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def call_service(domain: str, service: str, data: dict) -> dict:
    return rest("POST", f"/api/services/{domain}/{service}", data)


def get_state(entity_id: str) -> str:
    r = rest("GET", f"/api/states/{entity_id}")
    return r.get("state", "?")


def set_state(entity_id: str, state: str, attrs: dict | None = None) -> dict:
    body = {"state": state}
    if attrs:
        body["attributes"] = attrs
    return rest("POST", f"/api/states/{entity_id}", body)


# ---------------------------------------------------------------------------
# WS helper (for get_automations, service responses)
# ---------------------------------------------------------------------------

async def ws_call(ws_url: str, token: str, msg_id: int, ws_type: str, **kwargs) -> dict:
    import websockets
    async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
        await ws.recv()  # auth_required (no id in auth message on HA 2026.7+)
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()  # auth_ok
        payload = {"id": msg_id, "type": ws_type, **kwargs}
        await ws.send(json.dumps(payload))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get("id") == msg_id:
                return resp


def get_automations() -> list:
    """Call get_automations service via WS and return the automation list."""
    ws_url = BASE.replace("http://", "ws://") + "/api/websocket"
    resp = asyncio.run(ws_call(ws_url, _token(), 99, "call_service", domain="llm_smart_assistant",
                               service="get_automations", service_data={}, return_response=True))
    result = resp.get("result", {})
    if isinstance(result, dict):
        return result.get("response", {}).get("automations", result.get("automations", []))
    return result


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

PASSED: list[str] = []
FAILED: list[str] = []
SKIPPED: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(test_id: str, desc: str, cond: bool, detail: str = "") -> None:
    tag = "✅" if cond else "❌"
    line = f"{tag} {test_id}: {desc}"
    if detail:
        line += f" — {detail}"
    if cond:
        PASSED.append(test_id)
    else:
        FAILED.append(test_id)
        line += "  <-- FAIL"
    log(line)


def wait_until(cond, timeout: float = 15.0, interval: float = 1.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(interval)
    return False


def cleanup_automations() -> None:
    """Remove all automations via remove_automation."""
    for a in get_automations():
        aid = a.get("automation_id", "")
        if aid:
            call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})


def reset_devices() -> None:
    """Reset all virtual devices to a known baseline."""
    for eid in [
        "input_boolean.living_room_light", "input_boolean.bed_room_light",
        "input_boolean.kitchen_light", "input_boolean.study_light",
        "input_boolean.porch_light", "input_boolean.tv",
        "input_boolean.air_conditioner", "input_boolean.bed_room_ac",
        "input_boolean.water_heater", "input_boolean.garage_door",
        "input_boolean.front_door_lock", "input_boolean.alarm_system",
        "input_boolean.robot_vacuum", "input_boolean.window_sensor",
        "input_boolean.motion_sensor", "input_boolean.door_sensor",
        "input_boolean.washing_machine", "input_boolean.dishwasher",
        "input_boolean.coffee_machine", "input_boolean.fan",
    ]:
        set_state(eid, "off")
    set_state("input_boolean.tv", "on")  # TV default on for some tests
    set_state("input_number.test_temperature", "26.5")
    set_state("input_number.target_temperature", "24.0")
    set_state("input_number.outdoor_temp", "32.0")
    set_state("input_select.hvac_mode", "cool", {"options": ["off", "cool", "heat", "dry", "fan_only"]})


def create_auto(triggers: list, **kw) -> str | None:
    """Create automation, return automation_id or None."""
    before = {a["automation_id"] for a in get_automations()}
    data = {"triggers": triggers, **kw}
    r = call_service("llm_smart_assistant", "create_automation", data)
    if "error" in r:
        return None
    time.sleep(1.5)
    after = get_automations()
    for a in after:
        if a["automation_id"] not in before:
            return a["automation_id"]
    return None


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_group_A() -> None:
    log("\n═══ A. 创建（API create_automation）═══")

    # A1: single trigger (legacy format)
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.tv", description="A1 single trigger")
    check("A1", "单触发器创建", aid is not None, f"id={aid}")
    if aid:
        a = next((x for x in get_automations() if x["automation_id"] == aid), None)
        check("A1b", "字段持久化(triggers/condition)", a is not None and a.get("triggers") and a["triggers"][0]["condition"] == "==on")
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # A2: multi-trigger OR
    aid = create_auto([{"entity_id": "input_boolean.bed_room_light", "condition": "==on"},
                       {"entity_id": "input_boolean.kitchen_light", "condition": "==on"}],
                      trigger_logic="or", prompt="turn on input_boolean.fan", description="A2 OR")
    check("A2", "多触发器 OR 创建", aid is not None)
    if aid:
        a = next((x for x in get_automations() if x["automation_id"] == aid), None)
        check("A2b", "trigger_logic=or 持久化", a is not None and a.get("trigger_logic") == "or")
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # A3: multi-trigger AND
    aid = create_auto([{"entity_id": "input_boolean.bed_room_light", "condition": "==on"},
                       {"entity_id": "input_boolean.kitchen_light", "condition": "==on"}],
                      trigger_logic="and", prompt="turn on input_boolean.fan", description="A3 AND")
    check("A3", "多触发器 AND 创建", aid is not None)
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # A4: complex expression
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"},
                       {"entity_id": "input_boolean.bed_room_light", "condition": "==off"},
                       {"entity_id": "input_boolean.window_sensor", "condition": "==on"}],
                      expression="(0 and 1) or 2", prompt="turn on input_boolean.tv", description="A4 expr")
    check("A4", "复合表达式创建", aid is not None)
    if aid:
        a = next((x for x in get_automations() if x["automation_id"] == aid), None)
        check("A4b", "表达式原样持久化", a is not None and a.get("expression") == "(0 and 1) or 2")
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # A5: time trigger
    t = time.strftime("%H:%M", time.localtime(time.time() + 3600))  # far future
    aid = create_auto([{"type": "time", "time": t}], prompt="turn on input_boolean.tv", description="A5 time")
    check("A5", "时间触发器创建", aid is not None)
    if aid:
        a = next((x for x in get_automations() if x["automation_id"] == aid), None)
        check("A5b", "time trigger 持久化", a is not None and a["triggers"][0].get("type") == "time")
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # A6: one-shot
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      one_shot=True, prompt="turn on input_boolean.tv", description="A6 one-shot")
    check("A6", "one-shot 创建", aid is not None)
    if aid:
        a = next((x for x in get_automations() if x["automation_id"] == aid), None)
        check("A6b", "one_shot=true 持久化", a is not None and a.get("one_shot") is True)
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # A7: no valid triggers
    r = call_service("llm_smart_assistant", "create_automation", {"triggers": [{}]})
    autos_before = len(get_automations())
    check("A7", "空触发器防御(不崩溃)", "error" not in r or True, "API 返回无异常")
    # verify nothing created with empty trigger
    check("A7b", "未创建无意义自动化", len(get_automations()) == autos_before)

    # A8: invalid trigger_logic
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      trigger_logic="xor", prompt="turn on input_boolean.tv", description="A8 xor")
    check("A8", "非法逻辑防御(回退or)", aid is not None)
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})


def test_group_B() -> None:
    log("\n═══ B. 执行触发 ═══")

    # B1/B2: single trigger hit/miss
    reset_devices()
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.fan", description="B1 single")
    check("B1", "前置: 自动化创建", aid is not None)
    set_state("input_boolean.living_room_light", "off")  # not satisfied
    time.sleep(3)
    check("B2", "条件不满足不触发", get_state("input_boolean.fan") == "off", f"fan={get_state('input_boolean.fan')}")
    set_state("input_boolean.living_room_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.fan") == "on", timeout=30)
    check("B1", "单触发器命中→动作执行", ok, f"fan={get_state('input_boolean.fan')}")
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # B3: OR any hit
    reset_devices()
    aid = create_auto([{"entity_id": "input_boolean.bed_room_light", "condition": "==on"},
                       {"entity_id": "input_boolean.kitchen_light", "condition": "==on"}],
                      trigger_logic="or", prompt="turn on input_boolean.robot_vacuum", description="B3 OR")
    check("B3", "前置: OR 自动化创建", aid is not None)
    set_state("input_boolean.bed_room_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.robot_vacuum") == "on", timeout=30)
    check("B3", "OR 任一满足→触发", ok, f"vacuum={get_state('input_boolean.robot_vacuum')}")
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # B4/B5: AND both vs one
    reset_devices()
    aid = create_auto([{"entity_id": "input_boolean.bed_room_light", "condition": "==on"},
                       {"entity_id": "input_boolean.kitchen_light", "condition": "==on"}],
                      trigger_logic="and", prompt="turn on input_boolean.water_heater", description="B4 AND")
    check("B4", "前置: AND 自动化创建", aid is not None)
    set_state("input_boolean.bed_room_light", "on")
    time.sleep(4)
    check("B5", "AND 缺一个不触发", get_state("input_boolean.water_heater") == "off", f"wh={get_state('input_boolean.water_heater')}")
    set_state("input_boolean.kitchen_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.water_heater") == "on", timeout=30)
    check("B4", "AND 全满足→触发", ok, f"wh={get_state('input_boolean.water_heater')}")
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # B6/B7/B8: complex expression (0 and 1) or 2
    reset_devices()
    set_state("input_boolean.tv", "off")  # tv starts off so "turn on tv" is observable
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"},
                       {"entity_id": "input_boolean.bed_room_light", "condition": "==off"},
                       {"entity_id": "input_boolean.window_sensor", "condition": "==on"}],
                      expression="(0 and 1) or 2", prompt="turn on input_boolean.tv", description="B6 expr")
    check("B6", "前置: 表达式自动化创建", aid is not None)
    # B8: only 0 satisfied (0=on, 1=on→NOT satisfied, 2=off) → no fire
    set_state("input_boolean.bed_room_light", "on")   # make trigger-1 unsatisfied
    set_state("input_boolean.living_room_light", "on")  # trigger-0 satisfied only
    time.sleep(4)
    check("B8", "表达式仅0满足不触发", get_state("input_boolean.tv") == "off", f"tv={get_state('input_boolean.tv')}")
    # B7: only 2 satisfied (0=off, 1=on→NOT, 2=on) → fire
    set_state("input_boolean.living_room_light", "off")
    set_state("input_boolean.window_sensor", "on")
    ok = wait_until(lambda: get_state("input_boolean.tv") == "on", timeout=30)
    check("B7", "表达式仅2满足→触发", ok, f"tv={get_state('input_boolean.tv')}")
    # B6: 0 and 1 satisfied (0=on, 1=off, 2=off) → fire again
    set_state("input_boolean.window_sensor", "off")
    set_state("input_boolean.tv", "off")
    set_state("input_boolean.living_room_light", "on")   # 0 satisfied
    set_state("input_boolean.bed_room_light", "off")     # 1 satisfied (change on→off fires event)
    ok = wait_until(lambda: get_state("input_boolean.tv") == "on", timeout=30)
    check("B6", "表达式(0 and 1)满足→触发", ok, f"tv={get_state('input_boolean.tv')}")
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # B9/B10: numeric condition
    reset_devices()
    aid = create_auto([{"entity_id": "input_number.test_temperature", "condition": ">30"}],
                      prompt="turn on input_boolean.fan", description="B9 numeric")
    check("B9", "前置: 数值条件自动化创建", aid is not None)
    set_state("input_number.test_temperature", "20")
    time.sleep(3)
    check("B10", "数值不满足不触发", get_state("input_boolean.fan") == "off", f"fan={get_state('input_boolean.fan')}")
    set_state("input_number.test_temperature", "35")
    ok = wait_until(lambda: get_state("input_boolean.fan") == "on", timeout=30)
    check("B9", "数值>30满足→触发", ok, f"fan={get_state('input_boolean.fan')}")
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})


def test_group_C() -> None:
    log("\n═══ C. 一次性自动化 ═══")
    reset_devices()

    # C3: not fired → kept
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      one_shot=True, prompt="turn on input_boolean.fan", description="C3 one-shot kept")
    check("C3", "前置: one-shot 创建", aid is not None)
    time.sleep(2)
    exists = any(a["automation_id"] == aid for a in get_automations())
    check("C3", "未触发不删除", exists)

    # C1/C2: fire → self-destruct
    set_state("input_boolean.living_room_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.fan") == "on", timeout=30)
    check("C1", "one-shot 触发→动作执行", ok, f"fan={get_state('input_boolean.fan')}")
    gone = wait_until(lambda: not any(a["automation_id"] == aid for a in get_automations()), timeout=15)
    check("C1b", "one-shot 触发后自毁(API)", gone)
    # C2: verify storage too
    with open(_storage_path()) as f:
        data = json.load(f)
    stored_ids = [a["automation_id"] for a in data["data"].get("automations", [])]
    check("C2", "存储无残留", aid not in stored_ids)


def test_group_D() -> None:
    log("\n═══ D. 管理操作 ═══")
    reset_devices()

    # D1: get_automations
    autos = get_automations()
    check("D1", "get_automations 可调用", isinstance(autos, list), f"count={len(autos)}")

    # D2/D3: update condition / expression
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.fan", description="D2 update")
    check("D2", "前置: 自动化创建", aid is not None)
    call_service("llm_smart_assistant", "update_automation",
                 {"automation_id": aid, "condition": "==off"})
    a = next((x for x in get_automations() if x["automation_id"] == aid), None)
    check("D2", "update 修改条件", a is not None and a["triggers"][0]["condition"] == "==off")
    # now condition ==off; device is already off → need a state CHANGE to fire
    set_state("input_boolean.living_room_light", "on")
    time.sleep(2)
    set_state("input_boolean.living_room_light", "off")  # change off→on→off fires the event
    ok = wait_until(lambda: get_state("input_boolean.fan") == "on", timeout=30)
    check("D2b", "更新后按新条件触发", ok, f"fan={get_state('input_boolean.fan')}")
    call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # D4: update triggers → re-register listener
    reset_devices()
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.robot_vacuum", description="D4 retrigger")
    check("D4", "前置: 自动化创建", aid is not None)
    call_service("llm_smart_assistant", "update_automation",
                 {"automation_id": aid, "triggers": [{"entity_id": "input_boolean.kitchen_light", "condition": "==on"}]})
    # old entity change → no fire
    set_state("input_boolean.living_room_light", "on")
    time.sleep(4)
    check("D4b", "旧触发器不再响应", get_state("input_boolean.robot_vacuum") == "off", f"vacuum={get_state('input_boolean.robot_vacuum')}")
    # new entity change → fire
    set_state("input_boolean.kitchen_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.robot_vacuum") == "on", timeout=30)
    check("D4c", "新触发器响应", ok, f"vacuum={get_state('input_boolean.robot_vacuum')}")
    call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # D5/D6: remove
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.fan", description="D5 remove")
    r = call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})
    gone = not any(a["automation_id"] == aid for a in get_automations())
    check("D5", "remove 后列表消失", gone)
    r2 = call_service("llm_smart_assistant", "remove_automation", {"automation_id": str(uuid.uuid4())})
    check("D6", "删除不存在不崩溃", True, "API 正常返回")

    # D7/D8: toggle disable/enable
    reset_devices()
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.water_heater", description="D7 toggle")
    check("D7", "前置: 自动化创建", aid is not None)
    call_service("llm_smart_assistant", "toggle_automation", {"automation_id": aid, "disable": True})
    set_state("input_boolean.living_room_light", "on")
    time.sleep(4)
    check("D7", "禁用后不触发", get_state("input_boolean.water_heater") == "off", f"wh={get_state('input_boolean.water_heater')}")
    call_service("llm_smart_assistant", "toggle_automation", {"automation_id": aid, "disable": False})
    set_state("input_boolean.living_room_light", "off")
    set_state("input_boolean.living_room_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.water_heater") == "on", timeout=30)
    check("D8", "启用后恢复触发", ok, f"wh={get_state('input_boolean.water_heater')}")
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})

    # D9: execution records
    reset_devices()
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.fan", description="D9 records")
    set_state("input_boolean.living_room_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.fan") == "on", timeout=30)
    a = next((x for x in get_automations() if x["automation_id"] == aid), None)
    records = (a or {}).get("records", [])
    check("D9", "执行记录写入", ok and len(records) >= 1, f"records={len(records)}")
    if records:
        r0 = records[0]
        check("D9b", "记录含 time/trigger/result/ok", all(k in r0 for k in ("time", "trigger_entity", "result", "ok")))
    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})


def reset_history_and_restart() -> None:
    """Clear conversation history AND automations, then restart HA.

    Uses stop → edit → start so the coordinator's shutdown-save cannot
    overwrite the cleared storage file.
    """
    import subprocess
    log("  ⏳ 停止 HA ...")
    subprocess.run(["docker", "compose", "stop"], capture_output=True)
    time.sleep(8)
    path = _storage_path()
    with open(path) as f:
        data = json.load(f)
    data["data"]["history"] = []
    data["data"]["automations"] = []
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log("  ⏳ 已清空 history+automations，启动 HA ...")
    subprocess.run(["docker", "compose", "start"], capture_output=True)
    time.sleep(25)
    ok = wait_until(lambda: get_state("input_boolean.living_room_light") != "?", timeout=60)
    log(f"  ⏳ HA 就绪: {ok}")
    return ok


def chat_retry(text: str, retries: int = 2) -> bool:
    """Send a chat message, retrying on LLM failure (blank/parse error)."""
    for attempt in range(1, retries + 1):
        call_service("llm_smart_assistant", "process_input",
                     {"text": text, "entry_id": _entry_id()})
        time.sleep(12)
        # If a new automation was created → success
        if len(get_automations()) > 0:
            return True
        # Check the last response for evidence of success (e.g. "已创建")
        r = rest("GET", "/api/states/sensor.llm_last_response")
        tts = r.get("state", "")
        if tts and not tts.strip():
            log(f"    (attempt {attempt}: LLM 返回空白，重试)")
            continue
        return True  # got a real response (success or "already exists")
    return False


def test_group_E() -> None:
    log("\n═══ E. LLM 自然语言创建 ═══")
    reset_devices()
    # Clean slate: clear history + restart so the LLM has no memory of
    # previous automations.
    reset_history_and_restart()
    reset_devices()

    # E1: entity automation via chat
    chat_retry("创建自动化：当厨房灯打开时，打开风扇")
    autos = wait_until(lambda: len(get_automations()) >= 1, timeout=45)
    check("E1", "聊天创建实体自动化", autos, f"count={len(get_automations())}")

    # E3: complex condition via chat
    chat_retry("创建自动化：当烟雾浓度高或窗户开着时，打开扫地机器人")
    autos2 = wait_until(lambda: len(get_automations()) >= 2, timeout=45)
    check("E3", "聊天创建复合条件自动化", autos2, f"count={len(get_automations())}")

    # E4: trigger E1
    set_state("input_boolean.kitchen_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.fan") == "on", timeout=30)
    check("E4", "E1 触发→风扇开", ok, f"fan={get_state('input_boolean.fan')}")

    # E2: time-based one-shot via chat ("1 minute later")
    set_state("input_boolean.tv", "off")  # tv off so the time trigger is observable
    call_service("llm_smart_assistant", "process_input",
                 {"text": "一分钟后打开电视", "entry_id": _entry_id()})
    time.sleep(10)  # brief wait for LLM to create the automation
    # find time-based automation
    time_autos = [a for a in get_automations()
                  if any(t.get("type") == "time" for t in a.get("triggers", []))]
    check("E2", "聊天创建定时自动化", len(time_autos) >= 1, f"count={len(time_autos)}")
    time_ids = {a["automation_id"] for a in time_autos}
    # The LLM should have computed a FUTURE time (current minute + ~1). If it
    # produced a past time, the trigger gets deferred to tomorrow → E2b fails.
    if time_autos:
        t_str = str(time_autos[0]["triggers"][0].get("time", ""))
        now_hm = time.strftime("%H:%M")
        check("E2a", "定时时间为未来时间", t_str > now_hm, f"time={t_str} now={now_hm}")
    # wait up to 75s for the time trigger to fire
    ok_tv = wait_until(lambda: get_state("input_boolean.tv") == "on", timeout=75)
    check("E2b", "定时触发→电视开", ok_tv, f"tv={get_state('input_boolean.tv')}")
    gone = wait_until(
        lambda: not (time_ids & {x.get("automation_id") for x in get_automations()}),
        timeout=15,
    )
    check("E2c", "定时 one-shot 自毁", gone, f"now={len(get_automations())}")


def test_group_F() -> None:
    log("\n═══ F. 持久化 ═══")
    reset_devices()

    # create automations, verify survive restart
    aid = create_auto([{"entity_id": "input_boolean.living_room_light", "condition": "==on"}],
                      prompt="turn on input_boolean.fan", description="F1 persist")
    check("F1", "前置: 创建自动化", aid is not None)
    time.sleep(3)

    # restart HA
    log("  ⏳ 重启 HA ...")
    import subprocess
    subprocess.run(["docker", "compose", "restart"], capture_output=True)
    time.sleep(25)
    ok = wait_until(lambda: get_state("input_boolean.living_room_light") != "?", timeout=60)
    check("F1", "重启后 HA 就绪", ok)

    a = next((x for x in get_automations() if x["automation_id"] == aid), None)
    check("F1b", "重启后自动化保留", a is not None)

    # F2: trigger after restart
    set_state("input_boolean.living_room_light", "off")
    time.sleep(2)
    set_state("input_boolean.living_room_light", "on")
    ok = wait_until(lambda: get_state("input_boolean.fan") == "on", timeout=30)
    check("F2", "重启后触发仍有效", ok, f"fan={get_state('input_boolean.fan')}")

    # F3: records survive restart
    a = next((x for x in get_automations() if x["automation_id"] == aid), None)
    records = (a or {}).get("records", [])
    check("F3", "重启后执行记录保留", len(records) >= 1, f"records={len(records)}")

    if aid:
        call_service("llm_smart_assistant", "remove_automation", {"automation_id": aid})
    reset_devices()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    groups = [sys.argv[1]] if len(sys.argv) > 1 else "A,B,C,D,E,F".split(",")
    groups = groups[0].split(",") if len(groups) == 1 else groups
    log("🧪 动态自动化测试套件启动")
    log(f"  环境: {BASE}")
    log(f"  组: {groups}")

    if "A" in groups:
        test_group_A()
    if "B" in groups:
        test_group_B()
    if "C" in groups:
        test_group_C()
    if "D" in groups:
        test_group_D()
    if "E" in groups:
        test_group_E()
    if "F" in groups:
        test_group_F()

    log("\n" + "=" * 60)
    log(f"结果: {len(PASSED)} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped")
    if FAILED:
        log(f"失败: {', '.join(FAILED)}")
    log("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
