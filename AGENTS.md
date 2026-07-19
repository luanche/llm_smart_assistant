# LLM Smart Assistant — Project Prompt

You are developing a Home Assistant custom integration called **LLM Smart Assistant** (`custom_components/llm_smart_assistant/`).

## Repository

- **GitHub**: `https://github.com/luanche/llm_smart_assistant`
- **Remote**: `origin` → `git@github.com:luanche/llm_smart_assistant.git`

## Development Environment

- HA runs in Docker: `docker compose up -d` in project root
- Restart HA for Python changes: `docker compose restart`
- Panel files (`panel/index.html`, `panel/chat.js`) are read fresh on every request — no restart needed for HTML/JS changes
- HA at `http://localhost:8123`, credentials: `agent` / `password`

## Workflow

### Read First
- **`README.md`** — User-facing docs (installation, configuration, features)
- **`DEVELOP.md`** — Developer guide (architecture, hot-reload, i18n audit, design decisions)

### Code Changes
1. Understand the codebase before making changes
2. Run `python3 .pi/skills/i18n-audit/check.py` after any localization changes
3. Test via browser at `http://localhost:8123/llm-chat` (AI Chat panel)
4. Use available skills:
   - `.pi/skills/browser-mcp/` — Playwright browser automation for UI testing
   - `.pi/skills/ha-api/` — Home Assistant REST API calls
   - `.pi/skills/i18n-audit/` — i18n audit script

### Git
- Commit messages in English
- Clean commit history, one logical change per commit
- Keep `.gitignore` minimal; force-add only what should be tracked (e.g., `.pi/skills/`)

## Release Policy

**Do NOT create git tags or GitHub releases unless the user explicitly asks for it.**
Tags (`v*`) trigger the GitHub Actions release pipeline (`.github/workflows/release.yml`), which builds a zip and publishes a release. Only tag when the user says "release" or "打tag".

## Key Architecture

- **Multi-instance**: Each HA config entry is an independent LLM instance; services use `entry_id` for routing
- **Global services**: `process_input` and `toggle_automation` are registered once globally, not per-instance
- **AI Chat Panel**: Vanilla HTML/JS in iframe; multi-language via `LANGUAGES` object + `t()` function + `data-i18n` attributes
- **Dynamic Automations**: Created via LLM or UI; persisted in `.storage/llm_smart_assistant.storage`; use `async_track_state_change_event` for real-time triggers
- **ReAct Loop**: LLM gets states → acts → observes → repeats until steps empty
- **Security**: Domain + entity whitelist; action interceptor validates every LLM-requested action

## Language Policy

- Always respond in the user's language (English input → English output, Chinese input → Chinese output)
- Code comments, commit messages, and variable names in English
