#!/usr/bin/env python3
"""
i18n Audit Script for LLM Smart Assistant integration.
Run: python3 .pi/skills/i18n-audit/check.py

Checks all localization-related files for issues:
  - panel/index.html         → JS i18n keys, hardcoded strings, HTML labels
  - i18n keys ↔ translations → every i18n key in HTML has matching translation entry
  - translations/en.json     → English translation completeness
  - translations/zh-Hans.json → Chinese translation completeness vs en.json
  - config_flow.py           → Hardcoded UI labels in schema
  - const.py                 → Default prompts exist
  - services.yaml            → Service descriptions exist
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
COMPONENT_DIR = PROJECT_ROOT / "custom_components" / "llm_smart_assistant"

# ──────────────────────────────────────────────
#  Config
# ──────────────────────────────────────────────

# Strings that are OK to be hardcoded (not user-facing) in index.html
ALLOWED_HARDCODED = {
    # Browser API error codes / internal values
    "not-allowed",
    "Bearer ", "GET", "POST", "Authorization", "Content-Type",
    "application/json",
    "flex", "none", "fixed", "blur", "padding", "cover",
    "transform", "opacity", "inherit", "important",
    "active", "inline-block",
    "click", "keydown",
    "auto-card", "msg ", "msg assistant loading",
    "msg-text", "msg-time",
    "toggle-on", "toggle-off",
    "listening", "open",
    "user", "assistant", "option",
    "addConditionInput", "addEntityInput", "addModal", "addModalTitle",
    "addPromptInput", "autoContainer", "autoTab", "chatContainer", "chatTab",
    "confirmModal", "confirmText", "debugBtn", "debugContent", "debugModal",
    "debugModalClose", "editConditionInput", "editEntityInput", "editInput",
    "editModal", "editModalTitle", "emptyState", "emptyText", "hassTokens",
    "headerTitle", "inputField", "instanceSelect", "loadingIndicator",
    "progMsg", "sendBtn", "statusText",
    "tabBar", "voiceBtn",
    "auto", "chat", "message", "onclick",
    "Enter", "Escape",
    "SF Pro Text", "SF Pro Display", "SF Mono", "Microsoft YaHei", "PingFang SC",
    # LANGUAGES.en values (they are the source of truth, not hardcoded)
    "Debug", "Send", "Voice input", "Thinking...", "Action:", "Connected",
    "No token", "Token required", "Timed out, please retry",
    "(no response)", "Loading automations...",
    "No automations yet. Ask AI to create one!", "Listening...",
    "Voice input not supported in this browser",
    "Enter HA long-lived access token",
    "key",
    "Edit automation", "Add Automation", "Add", "Save", "Cancel",
    "Describe what action to take...", "Delete", "+ Add Automation",
    "Disabling...", "Enabling...", "Error: ",
    "No data yet.", "No action specified", "Auto: ",
    "Round", "Steps:", "TTS:", "(silent)",
    "Entity ID (trigger)", "Condition", "Action",
    "e.g., turn on input_boolean.air_conditioner", "Message...",
    "Delete this automation?", "Enable", "Disable", "Edit", "Delete",
    "Chat", "Automations",
    "Reasoning (round ", ")...",
    "sensor.living_room_temperature", ">30",
    "💡 Living room light", "📺 Turn off TV", "🌡️ Temperature", "🛏️ Bedroom light",
    # LANGUAGES.en keys (translation values, not hardcoded)
    "title"
    "empty"
    "connected"
    "noToken"
    "tokenRequired"
    "timeout"
    "noResponse"
    "autoLoading"
    "noAuto"
    "voiceHint"
    "voiceNotSupported"
    "round"
    "actions"
    "editPrompt"
    "addAutoTitle"
    "add"
    "save"
    "cancel"
    "editPromptPlaceholder"
    "deleteConfirmBtn"
    "addAuto"
    "disabling"
    "enabling"
    "errorPrefix"
    "noDebugData"
    "noActionSpecified"
    "autoPrefix"
    "debugRound"
    "debugSteps"
    "debugTts"
    "debugSilent"
    "labelEntityId"
    "labelCondition"
    "labelAction"
    "placeholderEntity"
    "placeholderCondition"
    "placeholderAction"
    "placeholderMsg"
    "deleteConfirm"
    "enable"
    "disable"
    "edit"
    "delete"
    "chat"
    "automations"
    "thinkingText"
    "tokenPromptText"
    "actionLabel"
    "reasoningPrefix"
    "reasoningSuffix"
    "debugBtnTitle"
    "voiceInputTitle"
    "sendTitle",
    # HTML tag names in applyI18n()
    "BUTTON", "INPUT", "LABEL", "SPAN", "TEXTAREA", "button",
    "text", "textarea",
    "sensor.living_room_temperature", ">30",
    "Turn on the living room light", "Turn off the TV",
    "What is the temperature?", "Open the bedroom light",
    "Turn on a light", "Turn off a device",
    "Enter HA long-lived access token",
    "key",
    "suggestion-btn", "suggestionButtons",
    "Status ",
    "Ask me to control your smart home devices...",
}

KNOWN_I18N_VALUES = {
    "AI Chat", "Connected", "No token", "Token required",
    "Timed out, please retry", "(no response)", "Loading automations...",
    "No automations yet. Ask AI to create one!", "Listening...",
    "Voice input not supported in this browser", "round", "actions",
    "Edit automation", "Add Automation", "Add", "Save", "Cancel", "Delete",
    "Describe what action to take...", "+ Add Automation",
    "Disabling...", "Enabling...", "Error: ",
    "No data yet.", "No action specified", "Auto: ",
    "Round", "Steps:", "TTS:", "(silent)",
    "Entity ID (trigger)", "Condition", "Action",
    "e.g., turn on input_boolean.air_conditioner", "Message...",
    "Delete this automation?", "Enable", "Disable", "Edit", "Delete",
    "Chat", "Automations",
    "💡 Living room light", "📺 Turn off TV", "🌡️ Temperature", "🛏️ Bedroom light",
    # LANGUAGES.en keys (translation values, not hardcoded)
    "title"
    "empty"
    "connected"
    "noToken"
    "tokenRequired"
    "timeout"
    "noResponse"
    "autoLoading"
    "noAuto"
    "voiceHint"
    "voiceNotSupported"
    "round"
    "actions"
    "editPrompt"
    "addAutoTitle"
    "add"
    "save"
    "cancel"
    "editPromptPlaceholder"
    "deleteConfirmBtn"
    "addAuto"
    "disabling"
    "enabling"
    "errorPrefix"
    "noDebugData"
    "noActionSpecified"
    "autoPrefix"
    "debugRound"
    "debugSteps"
    "debugTts"
    "debugSilent"
    "labelEntityId"
    "labelCondition"
    "labelAction"
    "placeholderEntity"
    "placeholderCondition"
    "placeholderAction"
    "placeholderMsg"
    "deleteConfirm"
    "enable"
    "disable"
    "edit"
    "delete"
    "chat"
    "automations"
    "thinkingText"
    "tokenPromptText"
    "actionLabel"
    "reasoningPrefix"
    "reasoningSuffix"
    "debugBtnTitle"
    "voiceInputTitle"
    "sendTitle",
}


def e(msg: str) -> None:    print(f"  ❌ {msg}")
def w(msg: str) -> None:    print(f"  ⚠️  {msg}")
def ok(msg: str) -> None:   print(f"  ✅ {msg}")
def section(title: str) -> None: print(f"\n─── {title} ───")


# ──────────────────────────────────────────────
#  Check: panel/index.html
# ──────────────────────────────────────────────

def check_index_html(path: Path) -> tuple[int, set, str]:
    """Returns (errors, defined_keys, html_content)."""
    section("panel/index.html")
    if not path.exists():
        e("File not found")
        return 1, set(), ""

    html = path.read_text(encoding="utf-8")
    errors = 0

    # 1a. i18n key coverage
    used = set(re.findall(r"i18n\.(\w+)", html))
    defined = set(re.findall(r"(\w+): isZh \?", html))
    missing = used - defined
    if missing:
        errors += len(missing)
        for k in sorted(missing):
            e(f"Missing i18n key: '{k}'")
    else:
        ok("All i18n keys defined")

    # 1b. Hardcoded user-facing strings
    # Collect spans to exclude:
    #   - t(keyName) calls (they use translation keys, not hardcoded text)
    #   - The LANGUAGES object definition (translation values, not hardcoded)
    t_call_spans = [(m.start(), m.end()) for m in re.finditer(r"(?<![.\w])t\('[A-Za-z][A-Za-z /,.!?-]*'\)", html)]
    
    # Find LANGUAGES object block boundaries
    lang_block_start = html.find('const LANGUAGES = {')
    lang_exclude_spans = []
    if lang_block_start >= 0:
        # Find the matching closing '};' by tracking brace depth
        depth = 0
        i = lang_block_start + len('const LANGUAGES = {')
        brace_started = False
        for i in range(lang_block_start, len(html)):
            ch = html[i]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    # Found the matching closing brace - the '};' after it
                    lang_exclude_spans.append((lang_block_start, i + 1))
                    break
    
    hardcoded = set()
    for m in re.finditer(r"'([A-Za-z][A-Za-z /,.\?!-]+)'", html):
        text = m.group(1)
        if text in ALLOWED_HARDCODED or text in KNOWN_I18N_VALUES:
            continue
        ctx = html[max(0, m.start() - 30):m.start()]
        if "isZh ?" in ctx or "i18n." in ctx:
            continue
        # Skip if inside a t('xxx') call
        in_t_call = any(start < m.start() < end for start, end in t_call_spans)
        if in_t_call:
            continue
        # Skip if inside the LANGUAGES object definition (translation values)
        in_lang_block = any(start < m.start() < end for start, end in lang_exclude_spans)
        if in_lang_block:
            continue
        if len(text) < 4 or text.startswith("http") or text.startswith("/api"):
            continue
        hardcoded.add(text)
    if hardcoded:
        errors += len(hardcoded)
        for s in sorted(hardcoded):
            e(f"Hardcoded string: '{s}'")
    else:
        ok("No hardcoded user-facing strings")

    # 1c. HTML hardcoded labels/placeholders
    html_issues = []
    for pattern, ptype in [
        (r'placeholder="([A-Z][^"]+)"', "placeholder"),
        (r'>([A-Z][A-Za-z /]{3,})</label>', "label"),
        (r'title="([A-Za-z][^"]+)"', "title"),
    ]:
        for m in re.finditer(pattern, html):
            text = m.group(1)
            if "${" in m.group(0):
                continue
            if text not in KNOWN_I18N_VALUES and text not in ALLOWED_HARDCODED:
                html_issues.append((ptype, text))
    if html_issues:
        errors += len(html_issues)
        for ptype, text in html_issues:
            e(f"Hardcoded HTML [{ptype}]: '{text}'")
    else:
        ok("No hardcoded HTML labels/placeholders")

    return errors, defined, html


# ──────────────────────────────────────────────
#  Check: i18n keys → translation entries
# ──────────────────────────────────────────────

def check_i18n_multilang(html: str) -> int:
    """Check the multi-language LANGUAGES object in index.html.
    Verifies that:
      - All t(keyName) calls reference keys that exist in LANGUAGES.en
      - LANGUAGES.zh has all keys that LANGUAGES.en has
      - Keys referenced via data-i18n also exist
    """
    section("i18n multi-language (LANGUAGES)")
    errors = 0

    # Extract LANGUAGES.en keys
    en_keys = set(re.findall(r'^\s+(\w+):\s', html, re.MULTILINE))
    # Filter to only keys inside the LANGUAGES.en block
    # Find where LANGUAGES.en starts and zh starts
    en_start = html.find('en: {')
    zh_start = html.find('zh: {')
    if en_start < 0 or zh_start < 0:
        e("Could not find LANGUAGES.en or LANGUAGES.zh definition")
        return 1
    
    # Get keys between en: { and the next language key (zh:)
    en_block = html[en_start:zh_start]
    en_keys = set(re.findall(r'^\s+(\w+):', en_block, re.MULTILINE))
    
    # Get keys in zh block  
    # zh block ends at the next '};' or end of file
    zh_block_end = html.find('};', zh_start)
    if zh_block_end < 0:
        zh_block_end = len(html)
    zh_block = html[zh_start:zh_block_end]
    zh_keys = set(re.findall(r'^\s+(\w+):', zh_block, re.MULTILINE))
    
    if not en_keys:
        e("No keys found in LANGUAGES.en")
        return 1
    
    ok(f"Found {len(en_keys)} keys in LANGUAGES.en")
    
    # Check zh has all en keys
    missing_zh = en_keys - zh_keys
    if missing_zh:
        errors += len(missing_zh)
        for k in sorted(missing_zh):
            e(f"zh missing key '{k}' (present in en)")
    else:
        ok(f"zh has all {len(en_keys)} en keys")
    
    # Check t(keyName) calls reference valid en keys
    t_refs = set(re.findall(r"(?<![.\w])t\(\'(\w+)\'?\)", html))
    invalid = t_refs - en_keys
    if invalid:
        errors += len(invalid)
        for k in sorted(invalid):
            e(f"t('{k}') references undefined key")
    
    # Check data-i18n attribute values reference valid en keys
    data_refs = set(re.findall(r'data-i18n="(\w+)"', html))
    invalid_data = data_refs - en_keys
    if invalid_data:
        errors += len(invalid_data)
        for k in sorted(invalid_data):
            e(f'data-i18n="{k}" references undefined key')
    
    # Check unused keys (defined but never referenced)
    all_refs = t_refs | data_refs
    unused = en_keys - all_refs
    if unused:
        w(f"Unused keys (defined but never referenced via t() or data-i18n): {', '.join(sorted(unused))}")
    
    return errors


# ──────────────────────────────────────────────
#  Check: translations/en.json ↔ zh-Hans.json
# ──────────────────────────────────────────────

def check_translations(path_en: Path, path_zh: Path) -> int:
    section("translations/")
    errors = 0

    if not path_en.exists() or not path_zh.exists():
        e("Translation file not found")
        return 1

    try:
        en = json.loads(path_en.read_text(encoding="utf-8"))
        zh = json.loads(path_zh.read_text(encoding="utf-8"))
    except json.JSONDecodeError as ex:
        e(f"JSON parse error: {ex}")
        return 1

    def flatten(d: dict, prefix: str = "") -> dict:
        result = {}
        for k, v in d.items():
            pk = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(flatten(v, pk))
            else:
                result[pk] = v
        return result

    en_flat = flatten(en)
    zh_flat = flatten(zh)

    missing_zh = set(en_flat) - set(zh_flat)
    if missing_zh:
        errors += len(missing_zh)
        for k in sorted(missing_zh):
            e(f"zh-Hans missing key: '{k}' (en: '{en_flat[k]}')")
    else:
        ok("zh-Hans has all en.json keys")

    orphan_zh = set(zh_flat) - set(en_flat)
    if orphan_zh:
        w(f"zh-Hans has orphan keys (not in en.json): {len(orphan_zh)}")
        for k in sorted(orphan_zh):
            w(f"  '{k}' = '{zh_flat[k]}'")

    empty_zh = [k for k in set(en_flat) & set(zh_flat) if not zh_flat[k].strip()]
    if empty_zh:
        errors += len(empty_zh)
        for k in empty_zh:
            e(f"Empty zh-Hans value for: '{k}' (en: '{en_flat[k]}')")
    else:
        ok("No empty Chinese translations")

    return errors


# ──────────────────────────────────────────────
#  Check: config_flow.py
# ──────────────────────────────────────────────

def check_config_flow(path: Path) -> int:
    section("config_flow.py")
    if not path.exists():
        e("File not found")
        return 1

    content = path.read_text(encoding="utf-8")
    errors = 0

    hardcoded_labels = set()
    for m in re.finditer(r'(label|name|title)\s*=\s*"([A-Za-z][^"]+)"', content):
        text = m.group(2)
        if "${" in m.group(0) or text.startswith("{"):
            continue
        hardcoded_labels.add(text)

    if hardcoded_labels:
        errors += len(hardcoded_labels)
        for s in sorted(hardcoded_labels):
            e(f"Hardcoded label: '{s}' (should use translation key)")
        w("Check if these labels have corresponding entries in en.json/zh-Hans.json")
    else:
        ok("No suspicious hardcoded labels")

    # Check translation key references exist in en.json
    tr_refs = set(re.findall(r'description\s*=\s*"([a-z_]+)"', content))
    if tr_refs:
        en_path = COMPONENT_DIR / "translations" / "en.json"
        if en_path.exists():
            en = json.loads(en_path.read_text(encoding="utf-8"))
            en_flat_keys = set()
            def _flatten_keys(d, prefix=""):
                for k, v in d.items():
                    pk = f"{prefix}.{k}" if prefix else k
                    if isinstance(v, dict):
                        _flatten_keys(v, pk)
                    else:
                        en_flat_keys.add(pk)
            _flatten_keys(en)
            missing_tr = tr_refs - en_flat_keys
            if missing_tr:
                errors += len(missing_tr)
                for k in sorted(missing_tr):
                    e(f"Translation key '{k}' referenced in config_flow but missing from en.json")
        else:
            w("en.json not found, skipping translation key check")

    return errors


# ──────────────────────────────────────────────
#  Check: const.py
# ──────────────────────────────────────────────

def check_const(path: Path) -> int:
    section("const.py")
    if not path.exists():
        e("File not found")
        return 1

    content = path.read_text(encoding="utf-8")
    errors = 0

    prompts = re.findall(r'(DEFAULT_PROMPT_\w+)\s*:\s*Final\s*=\s*"""(.+?)"""', content, re.DOTALL)
    if prompts:
        ok(f"Found {len(prompts)} default prompts")
        for name, text in prompts:
            text = text.strip()
            if not text:
                e(f"'{name}' is empty")
            elif len(text) < 50:
                w(f"'{name}' is very short ({len(text)} chars)")
    else:
        w("No DEFAULT_PROMPT_* found (may use different pattern)")

    return errors


# ──────────────────────────────────────────────
#  Check: services.yaml
# ──────────────────────────────────────────────

def check_services_yaml(path: Path) -> int:
    section("services.yaml")
    if not path.exists():
        e("File not found")
        return 1

    content = path.read_text(encoding="utf-8")
    errors = 0

    descriptions = re.findall(r'(name|description):\s*"([^"]+)"', content)
    if descriptions:
        ok(f"{len(descriptions)} service descriptions found")
    else:
        w("No explicit service descriptions found")

    return errors


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

def save_baseline(html: str) -> None:
    """Save current i18n keys as baseline for future diff."""
    keys = set(re.findall(r"(\w+): isZh ", html))
    baseline_path = Path(__file__).parent / ".i18n-baseline"
    baseline_path.write_text("\n".join(sorted(keys)) + "\n", encoding="utf-8")
    print(f"💾 Saved baseline with {len(keys)} i18n keys")


def diff_baseline(html: str) -> int:
    """Compare current i18n keys against saved baseline."""
    baseline_path = Path(__file__).parent / ".i18n-baseline"
    if not baseline_path.exists():
        w("No baseline file found. Run with --save-baseline first.")
        return 0
    baseline = set(baseline_path.read_text(encoding="utf-8").strip().split("\n"))
    current = set(re.findall(r"(\w+): isZh ", html))
    new_keys = current - baseline
    removed = baseline - current
    errors = 0
    if new_keys:
        print(f"  🆕 New i18n keys (not in baseline):")
        for k in sorted(new_keys):
            # Extract the English value
            m = re.search(rf"{k}: isZh \? '([^']*)' : '([^']*)'", html)
            if m:
                print(f"      {k}: cn='{m.group(1)}' en='{m.group(2)}'")
            else:
                print(f"      {k}")
        errors += len(new_keys)
    if removed:
        print(f"  🗑️  Removed i18n keys (in baseline but not found):")
        for k in sorted(removed):
            print(f"      {k}")
    if not new_keys and not removed:
        print(f"  ✅ No changes from baseline ({len(current)} keys)")
    return errors


def main() -> int:
    args = set(sys.argv[1:])

    print(f"🔍 i18n Audit — {COMPONENT_DIR.name}")
    print(f"   Path: {COMPONENT_DIR}\n")

    total_errors = 0

    # Check index.html and return i18n keys + html for next check
    html_err, defined_keys, html = check_index_html(COMPONENT_DIR / "panel" / "index.html")
    total_errors += html_err

    # Check i18n definition completeness (Chinese + English non-empty)
    total_errors += check_i18n_multilang(html)

    # Save baseline or diff
    if "--save-baseline" in args:
        save_baseline(html)
    if "--diff" in args:
        total_errors += diff_baseline(html)

    # Other checks
    total_errors += check_translations(
        COMPONENT_DIR / "translations" / "en.json",
        COMPONENT_DIR / "translations" / "zh-Hans.json",
    )
    total_errors += check_config_flow(COMPONENT_DIR / "config_flow.py")
    total_errors += check_const(COMPONENT_DIR / "const.py")
    total_errors += check_services_yaml(COMPONENT_DIR / "services.yaml")

    print(f"\n{'=' * 50}")
    if total_errors == 0:
        print("✅ All checks passed!")
        return 0
    else:
        print(f"❌ {total_errors} issue(s) found")
        return 1


if __name__ == "__main__":
    sys.exit(main())
