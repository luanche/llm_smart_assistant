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

### New Environment Setup Checklist

Use the **`dev-setup` skill** — it automates all of the below and asks for missing credentials:

```bash
python3 .pi/skills/dev-setup/setup_env.py
```

Manual equivalent:

1. `docker compose up -d`
2. Complete HA onboarding (create `agent` account)
3. Create a long-lived access token (Profile → Security) → save to `/tmp/hass_token.txt`
4. Create the debug dashboard: `python3 .pi/skills/llm-test/setup_dashboard.py` → available at `/llm-devices`
5. Add the LLM Smart Assistant integration (Settings → Devices & Services)

## Workflow

### Read First
- **`README.md`** — User-facing docs (installation, configuration, features)
- **`docs/DEVELOP.md`** / **`docs/DEVELOP_EN.md`** — Developer guide (architecture, hot-reload, i18n audit, design decisions)

### Code Changes
1. Understand the codebase before making changes
2. Run `python3 .pi/skills/i18n-audit/check.py` after any localization changes
3. Test via browser at `http://localhost:8123/llm-chat` (AI Chat panel)
4. Use available skills:
   - `.pi/skills/dev-setup/` — New dev environment bootstrap (onboarding, token, dashboard, integration)
   - `.pi/skills/browser-mcp/` — Playwright browser automation for UI testing
   - `.pi/skills/ha-api/` — Home Assistant REST API calls
   - `.pi/skills/i18n-audit/` — i18n audit script
   - `.pi/skills/llm-test/` — Test/debug workflow with virtual devices

### Documentation Maintenance

- **Keep docs in sync**: When development/debugging reveals that any doc (`README.md`, `docs/DEVELOP*.md`, `TEST_FLOW.md`, skill `SKILL.md` files, or this file) is outdated or contradicts the code, update it in the same change.
- **NEVER edit `CHANGELOG.md`** — it is generated automatically by the release pipeline.
- **Keep skills healthy**: If a skill's instructions are wrong, stale, or awkward to use (bad paths, outdated commands, missing patterns), update/optimize the corresponding `SKILL.md`.

### Branch Naming Convention

| Prefix | Purpose | Version Bump |
|--------|---------|--------------|
| `feat/*` | New feature / enhancement | Minor (`1.2.3 → 1.3.0`) |
| `fix/*` | Bug fix | Patch (`1.2.3 → 1.2.4`) |
| `chore/*` | Maintenance, deps, config | Patch (`1.2.3 → 1.2.4`) |
| `refactor/*` | Code refactor (no behavior change) | Patch (`1.2.3 → 1.2.4`) |
| `docs/*` | Documentation only | **None** |
| `style/*` | Formatting, whitespace | **None** |
| `test/*` | Adding/fixing tests | **None** |
| `perf/*` | Performance improvement | Patch (`1.2.3 → 1.2.4`) |

### Git Workflow (GitHub Flow)

```
1. git checkout -b <prefix>/<description>    # Create branch from master
2. (work, commit, test)
3. git push origin <prefix>/<description>     # Push branch
4. Create Pull Request on GitHub → merge to master
```

**Rules:**
- Always branch from `master`
- Branch name must start with a valid prefix (`feat/`, `fix/`, `chore/`, etc.)
- Use lowercase kebab-case for branch names: `feat/add-tts-support`
- Squash merge recommended to keep master history clean
- **Do NOT commit directly to master** (except for trivial docs/config changes)
- **Do NOT create git tags manually** — the pipeline does it automatically
- **Do NOT delete existing tags** unless explicitly asked
- Commit messages in English, one logical change per commit
- Keep `.gitignore` minimal; force-add only what should be tracked (e.g., `.pi/skills/`)
- **Do NOT commit unless the user explicitly says "提交" or "commit"**

### Version Scheme (SemVer)

Version is stored in `custom_components/llm_smart_assistant/manifest.json`.

> **Format:** `MAJOR.MINOR.PATCH`

| Change | Bump | Example |
|--------|------|--------|
| Breaking / major overhaul | MAJOR | Manual only |
| New feature (`feat/*`) | MINOR | `1.2.3 → 1.3.0` |
| Bug fix / chore / refactor | PATCH | `1.2.3 → 1.2.4` |
| Docs / style / test | None | stays `1.2.3` |

> **MAJOR bump** is never automatic — must be done manually and communicated clearly to users.

## Release Pipeline

Triggered automatically when a PR is **merged to `master`** (i.e., push to master).

### What the pipeline does:
1. Detects the merged branch name from the merge commit
2. Determines version bump type from branch prefix
3. Bumps version in `manifest.json`
4. Commits the bump and creates a `vX.Y.Z` tag
5. Builds `llm_smart_assistant_vX.Y.Z.zip` archive
6. Updates `CHANGELOG.md` (prepends new version with commit list)
7. Creates a GitHub Release with the archive attached

## Key Architecture

- **Multi-instance**: Each HA config entry is an independent LLM instance; services use `entry_id` for routing
- **Global services**: `process_input` and `toggle_automation` are registered once globally, not per-instance
- **AI Chat Panel**: Vanilla HTML/JS in iframe; multi-language via `LANGUAGES` object + `t()` function + `data-i18n` attributes
- **Dynamic Automations**: Created via LLM or UI; persisted in `.storage/llm_smart_assistant.storage`; use `async_track_state_change_event` for real-time triggers
- **ReAct Loop**: LLM gets states → acts → observes → repeats until steps empty
- **Security**: Domain + entity whitelist; action interceptor validates every LLM-requested action
- **Prompt Split**: Hardcoded core (JSON format, actions, loop behavior) is NOT user-modifiable; user can only customize appended instructions
- **TTS**: Supports Standard (media_player), Xiaomi MIoT (`intelligent_speaker`), and Custom templates; auto-mute via DND/sleep switch or configurable mute entity
- **Voice Input**: Input sensors trigger `_async_process_user_input` on state change; duplicate detection with noise filtering for Xiaomi conversation sensor
- **Brand Icons**: `brand/icon.png` + `brand/logo.png` served by HA's brands API at `/api/brands/integration/llm_smart_assistant/`
- **`_OptionalEntitySelector`**: Custom `EntitySelector` subclass that accepts empty strings (used for optional entity fields)

## Language Policy

- Always respond in the user's language (English input → English output, Chinese input → Chinese output)
- Code comments, commit messages, and variable names in English
