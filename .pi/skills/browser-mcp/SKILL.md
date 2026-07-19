---
name: browser-mcp
description: |
  Browser automation via Playwright MCP tools. Use for navigating web pages,
  filling forms, clicking elements, taking screenshots, capturing accessibility
  snapshots, evaluating JavaScript, and debugging UI issues.
  Essential for testing web UIs, logging into sites, and inspecting page state.
---

# Browser MCP (Playwright Edge)

## Quick Reference

### Navigation & Auth
```bash
# Navigate to URL
playwright_edge_browser_navigate url="http://localhost:8123/path"

# Check current page snapshot
playwright_edge_browser_snapshot

# Login pattern (HA login page uses shadow DOM)
# 1. Type into fields
playwright_edge_browser_type target="input[type=text]" text="username"
playwright_edge_browser_type target="input[type=password]" text="password"
# 2. Click submit via evaluate (buttons are in shadow DOM)
playwright_edge_browser_evaluate function="() => { document.querySelector('button')?.click() }"

# Wait for elements/page to load
playwright_edge_browser_wait_for time=3
playwright_edge_browser_wait_for text="Welcome"   # Wait for text to appear
playwright_edge_browser_wait_for textGone="Loading" # Wait for text to disappear
```

### Interaction
```bash
# Click an element (use snapshot ref or CSS selector)
playwright_edge_browser_click target="[ref=f33e11]"   # Use snapshot reference
playwright_edge_browser_click target="button:has-text('Submit')"

# Hover
playwright_edge_browser_hover target="[ref=f33e11]"

# Type into input
playwright_edge_browser_type target="[ref=f2e16]" text="value"

# Fill multiple form fields at once
playwright_edge_browser_fill_form fields='[
  {"target":"#username","name":"Username","type":"textbox","value":"agent"},
  {"target":"#password","name":"Password","type":"textbox","value":"passward"}
]'

# Select dropdown option
playwright_edge_browser_select_option target="[ref=...]" values='["option1"]'

# Press keyboard key
playwright_edge_browser_press_key key="Enter"
playwright_edge_browser_press_key key="Escape"
```

### Inspection
```bash
# Get accessibility snapshot (structure + text, better than screenshot for interaction)
playwright_edge_browser_snapshot
# With depth limit
playwright_edge_browser_snapshot depth=3

# Search for text in page
playwright_edge_browser_find text="error message"
playwright_edge_browser_find regex="/Error.*/i"

# Take screenshot
playwright_edge_browser_take_screenshot type="png" scale="css"
playwright_edge_browser_take_screenshot type="png" fullPage=true filename="page.png"

# Get console messages
playwright_edge_browser_console_messages level="error"
playwright_edge_browser_console_messages level="warning"

# Track network requests
playwright_edge_browser_network_requests static=false
playwright_edge_browser_network_requests filter="/api/.*"
playwright_edge_browser_network_request index=1
playwright_edge_browser_network_request index=1 part="response-body"
```

### Tabs
```bash
# List open tabs
playwright_edge_browser_tabs action="list"

# Open new tab
playwright_edge_browser_tabs action="new" url="http://localhost:8123"

# Switch to tab
playwright_edge_browser_tabs action="select" index=0

# Close current tab
playwright_edge_browser_tabs action="close"
```

### Complex Operations (via run_code_unsafe)
When you need to run multi-step operations or access shadow DOM, use `run_code_unsafe`:

```javascript
// Login + navigate pattern
async (page) => {
  await page.goto('http://localhost:8123/auth/login');
  await page.waitForTimeout(1000);
  await page.evaluate(() => {
    document.querySelector('input[name=username]').value = 'agent';
    document.querySelector('input[name=password]').value = 'passward';
  });
  await page.click('button[type=submit]');
  await page.waitForTimeout(2000);
  await page.goto('http://localhost:8123/target-page');
  await page.waitForTimeout(2000);
}
```

```javascript
// Check shadow DOM content
async (page) => {
  return await page.evaluate(() => {
    const ha = document.querySelector('home-assistant');
    const root = ha?.shadowRoot;
    return root?.querySelector('...')?.textContent;
  });
}
```

## Patterns

### Pattern: Login to HA and check config page
```bash
1. playwright_edge_browser_navigate url="http://localhost:8123/auth/login"
2. playwright_edge_browser_type target="input[type=text]" text="agent"
3. playwright_edge_browser_type target="input[type=password]" text="passward"
4. playwright_edge_browser_click target="button:has-text('Log in')"
5. playwright_edge_browser_wait_for time=2
6. playwright_edge_browser_navigate url="http://localhost:8123/target-page"
7. playwright_edge_browser_snapshot
```

### Pattern: Debug API response
```bash
1. playwright_edge_browser_navigate url="http://localhost:8123/page"
2. playwright_edge_browser_network_requests filter="/api/.*"
3. playwright_edge_browser_network_request index=1 part="response-body"
```

### Pattern: Check if element exists
```bash
1. playwright_edge_browser_find text="specific text"
# Returns matching nodes with context - empty means not found
```

### Common Errors & Fixes
- `"target" does not match any elements` → Use snapshot ref or CSS selector from the page snapshot
- **Shadow DOM not accessible** → Use `browser_run_code_unsafe` with `page.evaluate()`
- **Auth redirect** → Need to log in first or use token-based auth
- **Timeout** → Increase wait time or check if element exists
- `Extra data: line 1 column 4` → Response is an array `[]` instead of object `{}` - parse differently
