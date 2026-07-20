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

# Wait for elements/page to load
playwright_edge_browser_wait_for time=3
playwright_edge_browser_wait_for text="Welcome"   # Wait for text to appear
playwright_edge_browser_wait_for textGone="Loading" # Wait for text to disappear
```

### HA Login (Shadow DOM)

HA's login form uses LitElement web components (`<ha-input>`, `<ha-button>`) with shadow DOM.
Standard CSS selectors (`input[name=...]`) won't work. Use `page.getByRole()` instead.

**Login via `run_code_unsafe` (recommended):**
```javascript
async (page) => {
  // Navigate to root (redirects to /auth/authorize)
  await page.goto('http://localhost:8123/');
  await page.waitForTimeout(2000);
  
  // Fill fields by accessible role (works through shadow DOM)
  await page.getByRole('textbox', { name: /username/i }).fill('agent');
  await page.getByRole('textbox', { name: /password/i }).fill('password');
  await page.getByRole('button', { name: /log in/i }).click();
  
  // Wait for redirect after login
  await page.waitForTimeout(3000);
  
  // Navigate to target page
  await page.goto('http://localhost:8123/target-page');
  await page.waitForTimeout(2000);
}
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
  {"target":"#password","name":"Password","type":"textbox","value":"password"}
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
When you need to run multi-step operations, use `run_code_unsafe`:

```javascript
// Login + navigate to LLM Chat (recommended pattern)
async (page) => {
  await page.goto('http://localhost:8123/');
  await page.waitForTimeout(2000);
  
  // Use Playwright's built-in shadow DOM piercing via accessible roles
  await page.getByRole('textbox', { name: /username/i }).fill('agent');
  await page.getByRole('textbox', { name: /password/i }).fill('password');
  await page.getByRole('button', { name: /log in/i }).click();
  
  await page.waitForTimeout(3000);
  await page.goto('http://localhost:8123/llm-chat');
  await page.waitForTimeout(2000);
}
```

```javascript
// Check iframe content (LLM Chat panel)
async (page) => {
  const iframe = page.locator('iframe').contentFrame();
  const text = await iframe.locator('#headerTitle').textContent();
  return text;
}
```

```javascript
// Access shadow DOM directly (fallback when getByRole doesn't work)
async (page) => {
  return await page.evaluate(() => {
    const input = document.querySelector('ha-input[name=username]');
    return input?.shadowRoot?.querySelector('input')?.value;
  });
}
```

## Patterns

### Pattern: Login to HA and check page
```bash
1. playwright_edge_browser_run_code_unsafe code='
async (page) => {
  await page.goto("http://localhost:8123/");
  await page.waitForTimeout(2000);
  await page.getByRole("textbox", { name: /username/i }).fill("agent");
  await page.getByRole("textbox", { name: /password/i }).fill("password");
  await page.getByRole("button", { name: /log in/i }).click();
  await page.waitForTimeout(3000);
  await page.goto("http://localhost:8123/target-page");
  await page.waitForTimeout(2000);
}'
# Then take snapshot or screenshot
2. playwright_edge_browser_snapshot
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
- `"target" does not match any elements` → Use `page.getByRole()` or CSS selector. For shadow DOM elements (HA login), use `page.getByRole('textbox', { name: /label/i })` which pierces shadow boundaries.
- **`ref=fXX` selectors not working** → The `ref` engine is not supported. Use CSS selectors or `getByRole` instead.
- **Shadow DOM elements not found** → HA uses LitElement web components. Standard selectors may not work. Use:
  - `page.getByRole('textbox', { name: /username/i })` for inputs
  - `page.getByRole('button', { name: /log in/i })` for buttons
  - `page.evaluate()` + `shadowRoot.querySelector()` as fallback
- **Auth redirect loop** → Login using the pattern above, then navigate to target page
- **Timeout** → Increase wait time or check if element exists
- `Extra data: line 1 column 4` → Response is an array `[]` instead of object `{}` - parse differently
