# LLM Smart Assistant — Complete Test Flow

## Phase 1: Fresh Install
1. ✅ Delete existing config entry (API call)
2. ⚠️ Add integration via HA API flow (UI "Add Integration" button didn't respond to Playwright click)

## Phase 2: Configuration
3. ✅ Open Options flow via API
4. ✅ `prompt_default` shows short value (40 chars: `Reply in the SAME language as the user.`) — migration works
5. ❌ **Bug: `tts_entity_id` field uses EntitySelector** — rejects empty string / null. Changed to TextSelector.
6. ❌ **Bug: `history_time_window` max=1440** — sent 3600 minutes, got validation error. Max is 1440 (24h).
7. ✅ Options saved on retry

## Phase 3: Post-Setup Verification
8. ✅ Logs: setup completed, coordinator started, sensors added
9. ✅ Sensors `sensor.llm_last_response` and `sensor.llm_debug_raw` exist
10. ✅ Chat panel returns HTML (49KB)

## Phase 4: Chat Functionality
11. ✅ "turn on the bedroom light" → correct response
12. ✅ Chinese "关闭电视" → correct Chinese response
13. ✅ Multi-step "what's the temperature, then turn on the TV if it's above 25" → correct result

## Phase 5: Automation Management
14. ✅ `get_automations` service registered (returns `[]` via REST — HA REST API doesn't expose service response bodies)
15. ✅ `create_automation` service creates automation (confirmed in logs + storage file)
16. ✅ Automations persisted to `.storage/llm_smart_assistant.storage`

## Phase 6: Dynamic Suggestions
17. ⚠️ **Suggestions URL mismatch**: docs say `/{entry_id}/suggestions`, actual is `/suggestions?entry_id=xxx`
18. ✅ Returns suggestions array (3 items)
19. ❌ **Bug: Caching not working** — second call same speed (~3.1s) as first, different result

## Phase 7: Error Handling
20. ✅ Empty message: gracefully ignored (no message sent)

## Phase 8: Cleanup
21. ✅ Config entry deleted successfully

---

## Issues Found

### Bug 1: TTS Entity EntitySelector rejects empty value
- **File**: `config_flow.py` line ~228
- **Problem**: `selector.EntitySelector` for `tts_entity_id` validates that the value is a valid entity ID. Passing `""` or `null` causes error `"Entity X is neither a valid entity ID nor a valid UUID"` before it reaches the handler code that strips empty values.
- **Fix**: Changed from `EntitySelector` to `TextSelector` — empty string passes through, handler strips it.

### Bug 2: Suggestions caching broken
- **File**: `__init__.py` — `ChatSuggestionsView._cache`
- **Problem**: The class-level `_cache` dictionary uses a hash of entities/domains. Second call returns different data at same speed (~3.1s), suggesting cache is not being hit or is invalidated between calls.
- **Status**: Needs investigation — possibly the hash key generation changes or something clears the cache.

### Bug 3: Suggestions URL pattern inconsistency
- **File**: `__init__.py` — route registration
- **Problem**: The URL is `/api/llm_smart_assistant/suggestions?entry_id=xxx` but the summary/project documentation references `/api/llm_smart_assistant/{entry_id}/suggestions`. Need to update docs or add the alternative route.

### Issue 4: HA REST API doesn't return service response bodies
- **Problem**: Services registered with `supports_response` (like `get_automations`) return their response only via WebSocket API. The REST endpoint `/api/services/.../...` always returns `[]` regardless.
- **Status**: Not a bug — this is HA architecture. Use WebSocket or check storage directly for automation verification.

### Issue 5: UI button not clickable via Playwright
- **Problem**: The "Add integration" button in the HA UI didn't respond to Playwright clicks (both `locator.click()` and `browser_click`).
- **Status**: HA UI uses LitElement with Shadow DOM. Need `force=true` or direct DOM click.

### Fixed During Testing
- ✅ `tts_entity_id` selector changed from `EntitySelector` to `TextSelector`
