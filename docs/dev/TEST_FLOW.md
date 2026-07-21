# LLM Smart Assistant — Complete Test Flow

## Phase 1: Fresh Install
1. ✅ Delete existing config entry (API call)
2. ⚠️ Add integration via HA API flow (UI "Add Integration" button didn't respond to Playwright click)

## Phase 2: Configuration
3. ✅ Open Options flow via API
4. ✅ `prompt_default` shows short value (40 chars: `Reply in the SAME language as the user.`) — migration works
5. ✅ `tts_entity_id` field uses `_OptionalEntitySelector` (EntitySelector subclass that accepts empty value)
6. ✅ `history_time_window` max=1440 — sent 3600 minutes, got validation error. Max is 1440 (24h).
7. ✅ Options saved on retry
8. ✅ New fields: `tts_speak_volume`, `tts_mute_after`, `tts_mute_entity_id` all save correctly

## Phase 3: Post-Setup Verification
9. ✅ Logs: setup completed, coordinator started, sensors added
10. ✅ Sensors `sensor.llm_last_response` and `sensor.llm_debug_raw` exist
11. ✅ `sensor.llm_debug_raw` now exposes `prompt` attribute with system+user messages
12. ✅ Chat panel returns HTML (49KB)

## Phase 4: Chat Functionality
13. ✅ "turn on the bedroom light" → correct English response
14. ✅ Chinese "关闭电视" → correct Chinese response
15. ✅ Multi-step "what's the temperature, then turn on the TV if it's above 25" → correct result

## Phase 5: Multi-Language & i18n

### 5A: LLM Language Auto-Match
- [ ] **French**: "allume la lumière du salon" → response en français
- [ ] **Japanese**: "テレビをつけて" → response in 日本語
- [ ] **Mixed**: English message when HA language is zh-Hans → response in English (matches user's message)
- [ ] **Switch HA language to en** → change user's HA language via Profile → Language
- [ ] **Chat in Chinese while HA=English** → response still in Chinese (matches user's message, not HA config)

### 5B: Automation Language (Language: field)
- [ ] **Automation trigger message**: Verify LLM receives `Language:` field set to `hass.config.language`
- [ ] **Automation response language**: When HA=zh-Hans, automation description/prompt should be in Chinese
- [ ] **Fallback to `hass.config.language`**: When Language: field not parseable, LLM uses HA config language

### 5C: Suggestions Language
- ✅ **Suggestions in zh-Hans** (HA language = zh-Hans): Returns Chinese text
- [ ] **Suggestions in English** (when HA language = en): Verify response contains English text

### 5D: UI i18n (data-i18n + LANGUAGES)
- ✅ **56 keys in both en and zh** (confirmed by audit)
- [ ] **All 56 keys render**: No missing `{{key}}` placeholders visible in DOM
- [ ] **No hardcoded English strings**: Only `data-i18n` annotated text shows

### 5E: Translation File Completeness
- ✅ **i18n audit passes**: `python3 .pi/skills/i18n-audit/check.py` → all checks green
- ✅ **No empty zh translations**: Every key in `zh-Hans.json` has non-empty value
- ✅ **Config flow labels match**: Both `en.json` and `zh-Hans.json` have same set of `data` labels

### 5F: Config Flow in Chinese
- ✅ **Options flow with zh-Hans**: Shows Chinese labels like "附加聊天指令"
- ✅ **Options flow with en**: Shows English labels

## Phase 6: Automation Management
16. ✅ `get_automations` service registered (returns `[]` via REST — HA REST API doesn't expose service response bodies)
17. ✅ `create_automation` service creates automation (confirmed in logs + storage file)
18. ✅ Automations persisted to `.storage/llm_smart_assistant.storage`

## Phase 7: Dynamic Suggestions
19. ✅ Suggestions URL: `/api/llm_smart_assistant/suggestions?entry_id=xxx`
20. ✅ Returns suggestions array (3-6 items)
21. ✅ **Caching fixed** — switched from class-level `_cache` to module-level `_SUGGESTIONS_CACHE`. First call ~2.3s, second call **3ms** (cached).

## Phase 8: Error Handling & Resilience
22. ✅ Empty message: gracefully ignored (no message sent)
23. ✅ LLM JSON parse failure: now retries up to 3 times instead of immediate "Sorry"
24. ✅ LLM empty content: now retries instead of immediate None
25. ✅ All retries exhausted: returns `{"tts_text":"", "steps":[]}` fallback (no error prompt)
26. ✅ `max_tokens` default increased to 4096 (was 2048) to prevent JSON truncation

## Phase 9: Xiaomi Voice Input & TTS

### 9A: Voice Input Detection
27. ✅ `sensor.xiaomi_oh2p_35f4_conversation` detected as input sensor
28. ✅ Coordinator processes sensor state changes → sends to LLM
29. ✅ Duplicate/phantom detection: same-text updates ignored; appended noise (timestamps) ignored

### 9B: TTS Output
30. ✅ `xiaomi_miot.intelligent_speaker` service works (fixed from non-existent `play_text`)
31. ✅ Direct TTS call: "你好，这是一个测试语音播报" → speaker output confirmed
32. ✅ Full loop: voice input → LLM → TTS response → speaker speaks
33. ⚠️ Volume control: `media_player.volume_set` returns 200 but doesn't actually change volume
34. ✅ DND switch (`switch.*_no_disturb`) works for mute control
35. ✅ Sleep mode (`switch.*_sleep_mode`) available as fallback
36. ✅ User-configurable `tts_mute_entity_id` for custom mute control (EntitySelector)

## Phase 10: Cleanup
37. ✅ Config entry deleted successfully
