#!/usr/bin/env python3
"""Create the LLM Smart Assistant dev dashboard in Home Assistant.

Sets up a Lovelace dashboard at /llm-devices with all virtual test
devices and the integration's debug sensors. Idempotent: running it
again simply overwrites the dashboard config.

Usage:
    python3 .pi/skills/llm-test/setup_dashboard.py

Requires a long-lived token in .user/hass_token (relative to project root,
created by .pi/skills/dev-setup/setup_env.py — see .pi/skills/ha-api/SKILL.md).
"""

import asyncio
import json
import sys
from pathlib import Path

import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HA_URL = "ws://localhost:8123/api/websocket"
TOKEN_FILE = PROJECT_ROOT / ".user" / "hass_token"
DASHBOARD_URL_PATH = "llm-devices"

DASHBOARD_CONFIG = {
    "title": "智能设备",
    "views": [
        {
            "title": "智能设备",
            "icon": "mdi:devices",
            "cards": [
                {
                    "type": "entities",
                    "title": "💡 灯光",
                    "show_header_toggle": True,
                    "entities": [
                        "input_boolean.living_room_light",
                        "input_boolean.bed_room_light",
                        "input_boolean.kitchen_light",
                        "input_boolean.study_light",
                        "input_boolean.porch_light",
                    ],
                },
                {
                    "type": "entities",
                    "title": "❄️ 空调",
                    "show_header_toggle": True,
                    "entities": [
                        "input_boolean.air_conditioner",
                        "input_boolean.bed_room_ac",
                        "input_select.hvac_mode",
                        "input_select.fan_mode",
                        "input_select.ac_swing",
                        "input_number.target_temperature",
                        "input_number.fan_speed",
                    ],
                },
                {
                    "type": "entities",
                    "title": "🌡️ 传感器",
                    "entities": [
                        "sensor.ke_ting_wen_du",
                        "sensor.shi_wai_wen_du",
                        "sensor.shi_nei_shi_du",
                        "input_number.test_temperature",
                        "input_number.outdoor_temp",
                    ],
                },
                {
                    "type": "entities",
                    "title": "🔒 安防",
                    "show_header_toggle": True,
                    "entities": [
                        "input_boolean.front_door_lock",
                        "input_boolean.alarm_system",
                        "input_boolean.garage_door",
                    ],
                },
                {
                    "type": "entities",
                    "title": "🎮 其他",
                    "show_header_toggle": True,
                    "entities": [
                        "input_boolean.tv",
                        "input_boolean.water_heater",
                        "input_boolean.robot_vacuum",
                        "input_number.curtain_position",
                        "input_number.volume_level",
                    ],
                },
                {
                    "type": "entities",
                    "title": "🧪 调试",
                    "entities": [
                        {"entity": "sensor.test_voice_input", "name": "语音输入"},
                        {"entity": "sensor.llm_last_response", "name": "LLM 回复"},
                        {"entity": "sensor.llm_debug_raw", "name": "调试数据"},
                    ],
                },
            ],
        }
    ],
}


async def ws_call(ws, msg_id, payload):
    """Send a command and return the result."""
    await ws.send(json.dumps({"id": msg_id, **payload}))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == msg_id:
            if not resp.get("success"):
                raise RuntimeError(f"WS call failed: {resp}")
            return resp.get("result")


async def main():
    try:
        token = open(TOKEN_FILE).read().strip()
    except FileNotFoundError:
        sys.exit(f"Token file not found: {TOKEN_FILE} (see .pi/skills/ha-api/SKILL.md)")

    async with websockets.connect(HA_URL) as ws:
        # Auth handshake
        await ws.recv()  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth_resp = json.loads(await ws.recv())
        if auth_resp.get("type") != "auth_ok":
            sys.exit(f"Auth failed: {auth_resp}")

        msg_id = 1

        # 1. Create (or get) the dashboard
        try:
            await ws_call(ws, msg_id, {
                "type": "lovelace/dashboards/create",
                "url_path": DASHBOARD_URL_PATH,
                "title": "智能设备",
                "icon": "mdi:devices",
                "require_admin": False,
                "show_in_sidebar": True,
            })
            print(f"✅ Dashboard created: /{DASHBOARD_URL_PATH}")
        except RuntimeError as e:
            if "url_path" in str(e) or "exists" in str(e):
                print(f"ℹ️  Dashboard /{DASHBOARD_URL_PATH} already exists, updating config")
            else:
                raise
        msg_id += 1

        # 2. Save the dashboard config (idempotent overwrite)
        await ws_call(ws, msg_id, {
            "type": "lovelace/config/save",
            "url_path": DASHBOARD_URL_PATH,
            "config": DASHBOARD_CONFIG,
        })
        print("✅ Dashboard config saved")

    print(f"\n👉 Open http://localhost:8123/{DASHBOARD_URL_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
