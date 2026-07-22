---
name: browser-mcp
description: |
  Browser automation via Playwright MCP tools + Edge extension on Windows.
  pi (WSL) controls the browser via HTTP MCP protocol.
---

# Browser Automation (Playwright + Edge Extension)

## Setup

### Windows（一行启动）
```cmd
set "PLAYWRIGHT_MCP_EXTENSION_TOKEN=<你的token>" && npx @playwright/mcp@latest --port 3030 --host 0.0.0.0 --browser msedge --extension
```
> 注意 `set "VAR=value"` 的引号用法（CMD 语法）。
> Edge 需要安装 Playwright Extension。
> 防火墙需放行 3030 端口入站。

### WSL（pi 端）
通过 HTTP 直接调用 MCP server（`localhost:3030`）。无需额外扩展。

## Available Tools

所有工具通过 `browser_*` 命名，由 `@playwright/mcp` 提供：

| Tool | 用途 |
|------|------|
| `browser_navigate` | 导航到 URL |
| `browser_snapshot` | 页面无障碍快照（找元素 ref） |
| `browser_click` | 点击 |
| `browser_type` | 输入文字 |
| `browser_fill_form` | 批量填表 |
| `browser_take_screenshot` | 截图 |
| `browser_run_code_unsafe` | 执行任意 Playwright 代码 |
| `browser_press_key` | 按键 |
| `browser_hover` | 悬停 |
| `browser_find` | 搜索页面文字 |
| `browser_select_option` | 选择下拉选项 |
| `browser_tabs` | 标签页管理 |
| `browser_wait_for` | 等待 |
| `browser_evaluate` | 执行 JS 表达式 |

## Quick Reference

### HA 登录
```bash
browser_navigate url="http://localhost:8123"
browser_run_code_unsafe code="async (page) => { await page.getByRole('textbox', { name: /username/i }).fill('agent'); await page.getByRole('textbox', { name: /password/i }).fill('password'); await page.getByRole('button', { name: /log in/i }).click(); return 'done'; }"
browser_navigate url="http://localhost:8123/llm-chat"
```

### Shadow DOM（HA 用 LitElement）
HA 的 lit 组件用 CSS 选择器无效。必须用 `page.getByRole()` 或 `page.locator()`：

```javascript
// 正确：通过 accessible role 穿透 shadow DOM
page.getByRole('textbox', { name: /username/i }).fill('agent');
page.getByRole('button', { name: /log in/i }).click();

// 错误：CSS 选择器找不到 shadow DOM 元素
page.fill('#username', 'agent');  // ❌
```

### Iframe 内容（LLM Chat 面板）
LLM Chat 页面嵌在 `<iframe>` 中。先切换到 iframe 上下文：

```javascript
const iframe = page.locator('iframe').contentFrame();
const text = await iframe.locator('body').innerText();
```

### Run Code 技巧
- 简单的返回（`return page.url()`）直接返回结果
- 涉及 page 交互的代码（fill/click/goto）需要写在一个 `run_code_unsafe` 调用中
- 避免用 `waitForTimeout` 长等待，用 `browser_wait_for` 替代

## 架构
```
Windows                                              WSL (Docker)
┌──────────────┐         ┌──────────────────┐
│ Edge         │  ←ext→  │ @playwright/mcp  │  ←HTTP→  pi
│ + Extension  │         │ :3030            │
└──────────────┘         └──────────────────┘
```