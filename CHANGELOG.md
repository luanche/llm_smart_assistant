# Changelog

## v1.1.0

- feat: add workflow note to README
- fix: correct YAML syntax in release pipeline (multiline Python, quoted on)
- docs: remove duplicate blank entry in CHANGELOG.md
- chore: implement GitFlow-style branching and auto-release pipeline
- docs: update changelog for v1.0.1


## v1.0.1

- chore: add llm-test skill, fix RESTRICTED_DOMAINS, optimize prompts
- refactor: let LLM handle user confirmation via conversation (not code)
- feat: add user confirmation flow for call_service actions
- refactor: optimize HARDCODED_SYSTEM_PROMPT and HARDCODED_AUTOMATION_PROMPT
- feat: get_states now returns service descriptions and field definitions
- fix: i18n audit skill false positives for LANGUAGES values and API error codes
- feat: enhance get_states to return available services per entity
- refactor: move EN docs to docs/; rewrite system prompt with services list

## v1.0.0

- feat: bilingual docs (CN/EN separate files), improve voice error handling
- Only adjust volume/DND/sleep when tts_mute_after is enabled; otherwise speak directly
- Fix: also toggle DND/sleep switches even when mute_entity_id is set; restructure pre/post TTS actions
- Fix: remove prompt truncation in debug sensor (was limited to 500/300 chars)
- Remove entity limit in exposed_entities list - show all entities
- Fix: increase exposed entities limit from 100 to 500 to prevent truncation
- Fix hacs.json: remove zip_release, let HACS clone directly
- Reset version to 1.0.0 for clean release
- Fix release zip structure: include custom_components/ prefix for HACS
- Bump version to 1.1.1
- Add hacs.json for HACS custom repository support
- Bump version to 1.1.0
- Update docs: README, DEVELOP, AGENTS, TEST_FLOW with new features and fixes
- Remove duplicate root icon.png (brand/ is the canonical location)
- Add brand icons for integration dashboard; replace icon.svg with icon.png
- Use EntitySelector for tts_mute_entity_id; add icons.json for entity icons
- Fix debug icon, add prompt to debug modal, add mute entity config with sleep mode fallback
- Fix: robust duplicate detection for Xiaomi MIoT conversation sensor phantom updates
- Increase max_tokens to 4096 to prevent JSON truncation; retry on empty content
- Fix: use lowercase 'json' in prompts per DeepSeek JSON Output requirement
- Fix: retry on JSON parse failure instead of immediate None; return fallback response instead of None to avoid 'Sorry' error
- Fix anti-echo: use DND switch instead of volume_set (Xiaomi volume_set not effective)
- Add TTS speak volume + auto-mute after speak (anti-echo); xiaomi_miot intelligent_speaker fix
- Fix optional EntitySelector via _OptionalEntitySelector subclass; update gitignore for third-party integrations
- Fix suggestions caching (module-level cache) + fix tts_entity_id selector (EntitySelector→TextSelector) + add TEST_FLOW.md to gitignore
- Fix: tts_entity_id selector rejects empty value - use TextSelector instead of EntitySelector
- Migrate old prompts: detect old-format prompts in config flow and replace with new short defaults; coordinator backward-compatible fallback
- Split prompts: hardcoded system core (not user-modifiable) + user customization appended after it
- Fix LLM error & repetition: re-add response_format, delay speech to final round, increase max_tokens to 2048, conciser prompt, frontend poll timeout 30→60
- Fix consecutive chat: clear progMsg id between messages so AI creates new bubbles
- Pass HA user language to automation triggers via Language: field
- Dynamic suggestions: LLM-generated based on user devices, cached by entity config hash, respects HA user language
- Update automation prompt: fallback to Chinese when no user language detectable
- Fix const t variable shadowing bug, update prompts for language matching and silent intermediate rounds
- Fix HA password: passward → password (updated HA via UI, credentials file, SKILL.md, AGENTS.md)
- Add AGENTS.md project prompt for pi agent
- Fix manifest.json repo references, add GitHub Actions release pipeline
- Remove .user/ files from tracking (private data)
- Refine gitignore: track .pi/skills/ via force-add, ignore rest of .pi/
- Add DEVELOP.md with dev guide, architecture, hot-reload, i18n audit, key decisions
- Fix README: focus on plugin usage, remove dev/internal tooling references
- Rewrite README: remove outdated info, add AI Chat panel, multi-instance, data-i18n, automation management, service details
- Fix edit modal stray el> fragment
- Remove stray l>/el> text fragments from modal labels, fix double colon in action label
- Fix missing async function init() wrapper and substring i18n replacement bugs
- Fix stale HTML: read panel files on each request, add Cache-Control: no-cache headers
- Refactor i18n to multi-language LANGUAGES object with t() function, update audit script
- Auto i18n via data-i18n attributes: add applyI18n() function, remove manual JS assignments
- Fix i18n template literals in HTML body: move to JS init so they render correctly
- Final localization sweep: fix remaining (none) fallback, verify all i18n keys defined
- Fix automation disable: use coordinator's disabled set instead of config entry options, include in get_automations response
- Fix edit modal: add missing 3-field inputs (entity/condition/action), fix i18n labels
- Complete localization audit: fix all hardcoded English strings, add 18 missing i18n keys
- Fix modal button labels: Add/Edit modals show correct i18n text
- Fix automation disable/enable: actually remove/re-register state listeners
- Full automation edit (entity/condition/action), add automation UI, fix toggle visual update
- Fix iframe dialogs: custom confirm modal for delete, global toggle_automation with entry_id routing
- Replace window.prompt with custom modal for automation editing (works in iframe)
- Fix automation creation: add sensor default whitelist, handle LLM data format, add prompt to get_automations response
- Fix multi-instance service routing, auto-token acquisition via localStorage, add taste-skill premium UI design
- Config fixes: TTS selector, multi-mode history, automation editing, multi-instance selector
- Single-page config form, instance selector in chat panel, multi-instance support
- Richer config flow: 8 sections, editable API, entity selector, automation management, field descriptions
- Richer entity CSV: domain, name, state, unit, extra_attrs for LLM context
- Automation triggers: LLM-first with entity fallback, improved device context
- Automation: trigger execution, call_service format handling, configurable temperature sensor
- Revert requires_auth to False for panel static views (breaks panel loading when True)
- Final fixes: get_running_loop, safe_remove, auth, debounce, validation order, unused imports
