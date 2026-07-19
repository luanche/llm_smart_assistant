---
name: i18n-audit
description: Audits ALL localization files for the LLM Smart Assistant integration.
  Checks index.html (JS i18n keys, hardcoded strings, HTML labels), translation JSON files
  (key completeness, empty values), config_flow.py (hardcoded labels), const.py (prompts),
  and services.yaml (descriptions).
---

# i18n Audit Skill

## Usage

```bash
python3 .pi/skills/i18n-audit/check.py
```

## Files Checked

| File | What it checks |
|------|----------------|
| `panel/index.html` | i18n key coverage, hardcoded user-facing strings, HTML labels/placeholders |
| `translations/en.json` | Compared against zh-Hans.json for completeness |
| `translations/zh-Hans.json` | Missing keys vs en.json, empty translations |
| `config_flow.py` | Hardcoded selector labels that should use translation keys |
| `const.py` | Default prompts exist and are non-empty |
| `services.yaml` | Service descriptions exist |

## Output

- ✅ All clear when everything passes
- ❌ Lists each issue with details
