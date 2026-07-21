#!/usr/bin/env python3
"""Bootstrap a new LLM Smart Assistant dev environment.

Automates the full new-environment checklist:
  1. (optional) Start HA via docker compose
  2. Wait for HA to become ready
  3. Complete onboarding (create admin user) if needed
  4. Create a long-lived access token → /tmp/hass_token.txt
  5. Create the debug dashboard (/llm-devices)
  6. Add the LLM Smart Assistant integration (if LLM creds given)

Any missing info is asked interactively (or passed via CLI args).

Usage:
    python3 .pi/skills/dev-setup/setup_env.py [options]

Examples:
    # Fully interactive
    python3 .pi/skills/dev-setup/setup_env.py

    # Non-interactive
    python3 .pi/skills/dev-setup/setup_env.py \
        --ha-user agent --ha-password password \
        --llm-base-url https://api.deepseek.com/v1 \
        --llm-api-key sk-xxx --llm-model deepseek-chat

    # Environment only, no integration yet
    python3 .pi/skills/dev-setup/setup_env.py --skip-integration
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import websockets

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TOKEN_FILE = Path("/tmp/hass_token.txt")
CLIENT_ID_SUFFIX = "/"
DASHBOARD_SCRIPT = PROJECT_ROOT / ".pi/skills/llm-test/setup_dashboard.py"
DOMAIN = "llm_smart_assistant"


# ── Helpers ──────────────────────────────────────────────────────────────────

def info(msg):
    print(f"  {msg}")


def ok(msg):
    print(f"✅ {msg}")


def skip(msg):
    print(f"⏭️  {msg}")


def fail(msg):
    sys.exit(f"❌ {msg}")


def ask(prompt, arg_value, default=None, secret=False):
    """Return arg_value if given, else prompt interactively."""
    if arg_value:
        return arg_value
    hint = f" [{default}]" if default else ""
    fn = getpass.getpass if secret else input
    try:
        value = fn(f"❓ {prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        fail("Aborted.")
    return value or default


# ── Steps ────────────────────────────────────────────────────────────────────

def step_docker(start):
    print("\n── 1. Home Assistant container")
    if start:
        subprocess.run(["docker", "compose", "up", "-d"], cwd=PROJECT_ROOT, check=True)
        ok("docker compose up -d")
    else:
        skip("assuming container already managed (use --start-docker to auto-start)")


def step_wait_ready(ha_url, timeout=120):
    print("\n── 2. Wait for HA")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(ha_url, timeout=3, allow_redirects=False)
            if r.status_code in (200, 302):
                ok(f"HA ready at {ha_url}")
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    fail(f"HA not reachable at {ha_url} after {timeout}s")


def step_onboarding(ha_url, args):
    """Complete onboarding if needed. Returns an access token or None."""
    print("\n── 3. Onboarding")
    steps = requests.get(f"{ha_url}/api/onboarding", timeout=10).json()
    user_done = any(s["step"] == "user" and s["done"] for s in steps)
    if user_done:
        skip("already completed")
        return None

    username = ask("HA admin username", args.ha_user, default="agent")
    password = ask("HA admin password", args.ha_password, default="password", secret=True)
    name = username.capitalize()

    client_id = f"{ha_url}{CLIENT_ID_SUFFIX}"
    r = requests.post(f"{ha_url}/api/onboarding/users", json={
        "client_id": client_id,
        "name": name,
        "username": username,
        "password": password,
        "language": "zh-Hans",
    }, timeout=10)
    if r.status_code != 200:
        fail(f"User creation failed: {r.status_code} {r.text}")
    auth_code = r.json()["auth_code"]

    r = requests.post(f"{ha_url}/auth/token", data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": client_id,
    }, timeout=10)
    if r.status_code != 200:
        fail(f"Token exchange failed: {r.status_code} {r.text}")
    token = r.json()["access_token"]
    ok(f"Admin user '{username}' created")

    # Finish remaining onboarding steps
    for step in ("core_config", "analytics", "integration"):
        requests.post(f"{ha_url}/api/onboarding/{step}",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"client_id": client_id}, timeout=10)
    ok("Onboarding steps completed")
    return token


def step_token(ha_url, onboarding_token, args):
    """Ensure a valid long-lived token exists in TOKEN_FILE. Returns the token."""
    print("\n── 4. Long-lived access token")
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
        r = requests.get(f"{ha_url}/api/", headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if r.status_code == 200:
            ok(f"existing token valid ({TOKEN_FILE})")
            return token
        info("cached token invalid, creating a new one")

    # Need an access token to mint a long-lived one
    base_token = onboarding_token
    if not base_token:
        base_token = ask("Existing HA long-lived access token "
                         "(Profile → Security → Long-lived access tokens)",
                         args.ha_token, secret=True)
        if base_token:
            r = requests.get(f"{ha_url}/api/", headers={"Authorization": f"Bearer {base_token}"}, timeout=5)
            if r.status_code != 200:
                fail("Provided token is invalid")

    if onboarding_token:
        # Mint a real long-lived token via WebSocket
        async def mint():
            ws_url = ha_url.replace("http", "ws") + "/api/websocket"
            async with websockets.connect(ws_url) as ws:
                await ws.recv()
                await ws.send(json.dumps({"type": "auth", "access_token": onboarding_token}))
                auth = json.loads(await ws.recv())
                if auth.get("type") != "auth_ok":
                    fail(f"WS auth failed: {auth}")
                await ws.send(json.dumps({
                    "id": 1,
                    "type": "auth/long_lived_access_token",
                    "client_name": "dev-setup",
                    "lifespan": 3650,
                }))
                resp = json.loads(await ws.recv())
                if not resp.get("success"):
                    fail(f"Failed to mint long-lived token: {resp}")
                return resp["result"]
        token = asyncio.run(mint())
        ok("long-lived token created (10y)")
    else:
        token = base_token
        ok("using provided token")

    TOKEN_FILE.write_text(token + "\n")
    ok(f"token cached to {TOKEN_FILE}")
    return token


def step_dashboard():
    print("\n── 5. Debug dashboard")
    r = subprocess.run([sys.executable, str(DASHBOARD_SCRIPT)], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        fail(f"Dashboard setup failed: {r.stderr}")


def step_integration(ha_url, token, args):
    print("\n── 6. LLM Smart Assistant integration")
    if args.skip_integration:
        skip("--skip-integration")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    entries = requests.get(f"{ha_url}/api/config/config_entries/entry",
                           headers=headers, timeout=10).json()
    if any(e["domain"] == DOMAIN for e in entries):
        skip("integration already configured")
        return

    base_url = ask("LLM API Base URL", args.llm_base_url,
                   default="https://api.deepseek.com/v1")
    api_key = ask("LLM API Key", args.llm_api_key, secret=True)
    model = ask("LLM Model", args.llm_model, default="deepseek-chat")
    if not api_key:
        fail("LLM API Key is required (or use --skip-integration)")

    r = requests.post(f"{ha_url}/api/config/config_entries/flow",
                      headers=headers, json={"handler": DOMAIN}, timeout=10)
    flow = r.json()
    flow_id = flow.get("flow_id")
    if not flow_id:
        fail(f"Cannot start config flow: {flow}")

    r = requests.post(f"{ha_url}/api/config/config_entries/flow/{flow_id}",
                      headers=headers, json={
                          "title": "LLM Smart Assistant",
                          "api_base_url": base_url.rstrip("/"),
                          "api_key": api_key,
                          "model_name": model,
                      }, timeout=30)
    result = r.json()
    if result.get("type") == "create_entry":
        ok(f"integration added (model: {model})")
        info("Note: input_number/input_select are NOT in the default domain whitelist.")
        info("Adjust domains via Settings → Devices & Services → LLM Smart Assistant → Configure.")
    else:
        fail(f"Config flow failed: {result}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ha-url", default="http://localhost:8123")
    p.add_argument("--start-docker", action="store_true", help="run 'docker compose up -d' first")
    p.add_argument("--ha-user", help="HA admin username (onboarding)")
    p.add_argument("--ha-password", help="HA admin password (onboarding)")
    p.add_argument("--ha-token", help="existing long-lived access token (if already onboarded)")
    p.add_argument("--llm-base-url")
    p.add_argument("--llm-api-key")
    p.add_argument("--llm-model")
    p.add_argument("--skip-integration", action="store_true")
    args = p.parse_args()
    ha_url = args.ha_url.rstrip("/")

    print("🚀 LLM Smart Assistant — dev environment setup")
    step_docker(args.start_docker)
    step_wait_ready(ha_url)
    onboarding_token = step_onboarding(ha_url, args)
    token = step_token(ha_url, onboarding_token, args)
    step_dashboard()
    step_integration(ha_url, token, args)

    print("\n🎉 Done!")
    print(f"   HA:        {ha_url}")
    print(f"   Dashboard: {ha_url}/llm-devices")
    print(f"   AI Chat:   {ha_url}/llm-chat")


if __name__ == "__main__":
    main()
