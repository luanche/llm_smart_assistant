---
name: dev-setup
description: |
  Bootstrap a brand-new dev environment for this project. Use whenever the
  developer asks to set up / initialize / recreate a local dev environment.
  Handles docker, HA onboarding, tokens, dashboard, and integration config.
  Ask the developer for any missing credentials before running.
---

# Dev Environment Setup

One command to bootstrap a fresh dev environment from zero to ready.

## Information to Collect First

Ask the developer for anything missing **before** running the script:

| Info | Required | Default | Notes |
|------|----------|---------|-------|
| HA admin username | Only for fresh HA | `agent` | Project convention |
| HA admin password | Only for fresh HA | `password` | Project convention |
| LLM API Base URL | For integration | `https://api.deepseek.com/v1` | Any OpenAI-compatible API |
| LLM API Key | For integration | — | **Always ask**, never guess |
| LLM Model | For integration | `deepseek-chat` | e.g. `gpt-4o-mini` |

If the developer only wants the environment without the LLM integration, use `--skip-integration`.

## Usage

```bash
# Interactive (asks for anything missing)
python3 .pi/skills/dev-setup/setup_env.py

# Fully scripted
python3 .pi/skills/dev-setup/setup_env.py \
  --ha-user agent --ha-password password \
  --llm-base-url https://api.deepseek.com/v1 \
  --llm-api-key sk-xxx --llm-model deepseek-chat

# Env only (dashboard + token, no integration)
python3 .pi/skills/dev-setup/setup_env.py --skip-integration

# Include docker compose up -d
python3 .pi/skills/dev-setup/setup_env.py --start-docker
```

## What the Script Does

| Step | Action | Idempotent? |
|------|--------|-------------|
| 1. Docker | `docker compose up -d` (with `--start-docker`) | ✅ |
| 2. Wait | Poll HA until HTTP 200/302 (max 120s) | ✅ |
| 3. Onboarding | Create admin user + finish all steps, if not done | ✅ skips if done |
| 4. Token | Validate cached `/tmp/hass_token.txt`; otherwise mint a 10-year long-lived token via WebSocket | ✅ reuses valid token |
| 5. Dashboard | Run `llm-test/setup_dashboard.py` → `/llm-devices` | ✅ overwrites config |
| 6. Integration | Start config flow with LLM creds | ✅ skips if entry exists |

## After Setup

- HA: `http://localhost:8123`
- Debug dashboard: `http://localhost:8123/llm-devices`
- AI Chat panel: `http://localhost:8123/llm-chat`

Next: verify with a test command, e.g. via the `llm-test` skill ("打开厨房灯" → check `input_boolean.kitchen_light` turns on).

## Troubleshooting

- **Config flow validation error** — the flow probes `GET {base_url}/models`; some providers (e.g. Databricks serving endpoints) return 404 there, which is treated as OK. `401` = bad key, anything else = connection issue.
- **Token invalid** — delete `/tmp/hass_token.txt` and re-run; the script mints a new one (requires onboarding token or a provided `--ha-token`).
- **Integration already exists** — remove it first via `ha-api` skill (config entries API) if you want a clean reinstall.
