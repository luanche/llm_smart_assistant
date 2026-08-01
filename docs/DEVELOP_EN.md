# Development Guide

> [中文](DEVELOP.md)

---

## 🚀 Quick Start

```bash
# Start Home Assistant with the integration
docker compose up -d

# Check logs
docker compose logs -f

# Restart
docker compose restart

# Stop
docker compose down
```

### Debug Dashboard

Run once when setting up a new environment (idempotent) to create the `/llm-devices` debug dashboard (virtual device states + LLM debug sensors):

```bash
python3 .pi/skills/llm-test/setup_dashboard.py
```

---

## 📁 Code Structure

```
custom_components/llm_smart_assistant/
├── __init__.py           # Entry point, services, panel registration
├── manifest.json         # Dependencies and version
├── const.py              # Constants, default prompts
├── config_flow.py        # ConfigFlow (initial 4 fields) + single-page OptionsFlow (24 fields)
├── coordinator.py        # Core: LLM API, ReAct loop, automations
├── services.py           # Step executor with whitelist interceptor
├── sensor.py             # LLMLastResponseSensor + LLMDebugRawSensor
├── services.yaml         # Service definitions
├── icons.json
├── brand/
│   ├── icon.png
│   └── logo.png
├── panel/
│   ├── index.html        # AI Chat UI (vanilla JS, multi-language)
│   └── chat.js           # LitElement wrapper that creates the iframe
└── translations/
    ├── en.json
    └── zh-Hans.json
```

---

## 🔄 Hot Reloading

**Panel files (HTML/JS)**: `panel/index.html` and `panel/chat.js` are read from disk on every request. Edit them and refresh the browser — **no HA restart needed**.

**Python changes (`*.py`)**: Restart HA:

```bash
docker compose restart
```

---

## 💬 AI Chat Panel

### Architecture

The chat panel is a vanilla HTML/JS single-page app loaded in an iframe inside HA's sidebar.

```
HA Sidebar
  → panel_custom → chat.js (LitElement)
    → <iframe src="/api/llm_smart_assistant/chat_panel">
      → index.html (full UI)
```

### Multi-Language System

The panel uses a `LANGUAGES` object with a `t()` translate function:

```javascript
const LANGUAGES = {
  en: { title: 'AI Chat', ... },
  zh: { title: 'AI 聊天', ... },
  // Add new languages here
};

// Usage in JS
t('title')  // → 'AI Chat' or 'AI 聊天'

// Usage in HTML (auto-applied)
<button data-i18n="addAuto"></button>
```

**Adding a new language:**

1. Add an entry to the `LANGUAGES` object with all keys.
2. `applyI18n()` automatically picks it up based on `navigator.language`.
3. Fallback chain: full language → language root → `en`.

### Token Acquisition (iframed context)

The iframe gets the HA auth token through multiple fallback channels:

1. Backend-injected configured token (`window.CONFIGURED_ACCESS_TOKEN`, from the `access_token` config option)
2. `chat.js` passes it via URL query parameter (`?auth_token=...`)
3. Reads from `localStorage['hassTokens']` (same-origin, shared with parent)
4. PostMessage handshake with parent window
5. Falls back to a manual prompt

### Key Functions in index.html

| Function                      | Purpose                                                      |
| ----------------------------- | ------------------------------------------------------------ |
| `t(key)`                      | Translate a key to the active language                       |
| `applyI18n()`                 | Apply translations to all `[data-i18n]` elements             |
| `callAPI(method, path, body)` | HA REST API wrapper with auth header                         |
| `sendMessage()`               | Send user input, subscribe to the response sensor via WebSocket, display progressively |
| `subscribeEntity()`           | Subscribe to entity state changes via the HA WebSocket API                             |
| `refreshAutomations()`        | Fetch and render automation cards                            |
| `toggleAutomation()`          | Enable/disable an automation (optimistic UI, instant feedback)  |
| `showAddSheet()`              | Open add-automation bottom sheet           |
| `showEditSheet()`             | Open edit bottom sheet (entity, condition, action)        |
| `showDeleteConfirm()`         | Open delete confirmation bottom sheet        |
| `initHistory()`               | Load chat history (recorder API, lazy-loads older entries on scroll-to-top) |

---

## 🔍 i18n Audit

Run before committing to check all localization files:

```bash
# Run audit
python3 .pi/skills/i18n-audit/check.py

# Save baseline
python3 .pi/skills/i18n-audit/check.py --save-baseline

# Diff against baseline
python3 .pi/skills/i18n-audit/check.py --diff
```

Checks:

- `panel/index.html` — i18n key coverage, hardcoded strings
- `LANGUAGES.en` ↔ `LANGUAGES.zh` — key completeness
- `t('key')` calls — all reference valid keys
- `data-i18n` attributes — all reference valid keys
- `translations/en.json` ↔ `translations/zh-Hans.json` — key completeness
- `config_flow.py` — hardcoded labels vs translation keys
- `const.py` — default prompts exist
- `services.yaml` — descriptions exist

---

## 🔄 Integration Flow

### Message Processing

```
User Input (chat UI / service call / text sensor)
  → coordinator._async_process_user_input()
    → _build_context() (time, date, exposed entities CSV)
    → _async_query_llm() (API call with retry + exponential backoff)
    → Parse JSON response
    → _execute_steps() (validate + execute each action)
    → Update sensor.llm_last_response (progressive round-by-round)
    → Repeat until steps=[] or max iterations reached
  → Final TTS text stored in last_response
```

### Automation Trigger Flow

```
Entity state change
  → async_track_state_change_event fires
  → _async_handle_automation_event()
    → Check disabled list
    → Call LLM with automation context
    → Parse response → execute steps (or fallback entity name matching)
```

### Service Registration

`process_input` and `toggle_automation` are registered **globally** (once, on first setup).
Other services (`create_automation`, `remove_automation`, `get_automations`, `update_automation`, `chat`) are registered **per-instance**. The `chat` service is used by the chat panel backend and returns the LLM response synchronously.

---

## 🎯 Key Design Decisions

| Decision                                         | Rationale                                                                   |
| ------------------------------------------------ | --------------------------------------------------------------------------- |
| `process_input` is global                        | Multiple instances register the same service; use `entry_id` param to route |
| `toggle_automation` is global                    | Same reason — needs `entry_id` to find the right coordinator                |
| Panel files read on each request                 | Allows hot-reloading HTML/JS without HA restart                             |
| `data-i18n` attribute pattern                    | Adding a new string only requires one HTML attribute + one LANGUAGES entry  |
| Both count AND time history                      | Applies both constraints simultaneously for more precise history control    |
| WebSocket subscription instead of polling        | Pushes progressive LLM replies in real time; lower latency, fewer requests  |
| LLM format uses `entity_id`/`condition`/`prompt` | Simple, LLM-friendly structure for `create_automation`                      |
| Disable removes listener                         | Unlike a flag check, this actually stops the event system from firing       |
| History reads HA recorder (no cache)             | History survives restarts; all input sources recorded via `sensor.llm_last_input` (chat panel / service calls / voice sensors), merged with the response sensor into one timeline |
| History skips intermediate rounds                | Recorder dedupes identical states, so the final reply may equal the last round; use consecutive-dedup instead of in_progress filtering |
| History lazy-loads via `before` cursor           | Newest-first with cursor pagination; scroll-to-top loads older entries; cursor must be URL-encoded (`+` → space) |
| Automation `triggers` array                     | `[{entity_id, condition}]` or `[{type: time, time}]`; keeps legacy `entity_id`/`condition` properties for backward-compatible storage migration |
| Boolean `expression` (advanced)                 | Trigger indexes as numbers (`(0 and 1) or 2`); safe recursive-descent parser (no eval) supporting AND/OR/parentheses/precedence; falls back to trigger_logic when absent |
| AND logic re-checks ALL trigger states on change | When any trigger changes, evaluate **all** entity triggers' current states (not historical), avoiding cross-event state tracking |
| Time triggers auto-re-register daily            | After `async_track_point_in_time` fires, re-registers for the next day unless one-shot or disabled → supports "every day at 21:00" long-running schedules |
| One-shot auto-removes after firing              | Calls `async_remove_automation` after execution for one-time rules like "turn off AC in 1 minute" |
| Execution records ring buffer (30)              | Each firing writes time/trigger/result/ok/steps; persisted with the automation across restarts; dedicated debug sheet shows per-automation records |
| Multi-output `tts_entities` list                 | Task 4b: multiple TTS devices (with areas); prompt injects `## Output devices` (entity_id/name/area CSV); the LLM can add `output_device` in its JSON to pick the nearest speaker; legacy `tts_entity_id` kept (first device = default, old config auto-mirrored into the list) |
| Input-source marker + area resolution            | `process_input` accepts `source_entity`; `_get_area_name` resolves entity registry `area_id` → area registry name, injected as `## Input source`; the model picks an output device matching the user's area; AI Chat / service_call never TTS (browser speech) |
| `output_device` whitelist check                  | Only accepts devices inside `self.tts_entities` (prevents hallucinated IDs); falls back to the default device otherwise |
