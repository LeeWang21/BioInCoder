---
name: bioincoder-browser
description: Use BioInCoder BrowserAgent with agent-browser CLI and CloakBrowser as the default browser backend for low-context web browsing, page inspection, interaction, screenshots, and targeted extraction. Use when opening websites, verifying web pages, extracting page-level evidence, or handling slow/anti-bot pages with CloakBrowser.
metadata:
  tool_type: browser
  primary_tool: agent_browser_command
---

# BioInCoder Browser

Use this skill when BrowserAgent needs to browse a web page using `agent-browser` CLI with CloakBrowser as the default browser backend.

The goal is not to scrape everything. The goal is to complete the browser objective with the fewest commands and the least context.

## Runtime Configuration

On the server, configure these environment variables if needed:

- `BIOINCODER_AGENT_BROWSER_BIN`: agent-browser binary name or path. Default: `agent-browser`.
- `BIOINCODER_CLOAKBROWSER_BIN`: cloakbrowser binary name or path. Default: `cloakbrowser`.
- `BIOINCODER_CLOAKBROWSER_REQUIRED`: set to `1` to require CloakBrowser. Default: `1`.
- `BIOINCODER_CLOAKBROWSER_AUTO_CONFIG`: set to `1` to let BioInCoder compute CloakBrowser env vars from the installed Python package. Default: `1`.
- `AGENT_BROWSER_EXECUTABLE_PATH`: optional manual CloakBrowser binary path for agent-browser.
- `AGENT_BROWSER_ARGS`: optional manual CloakBrowser stealth args for agent-browser.

CloakBrowser's official agent-browser integration does not connect to an already-running CDP browser. agent-browser launches Chrome itself through env vars:

```bash
BINARY_PATH=$(python3 -c "from cloakbrowser.download import ensure_binary; print(ensure_binary())")
STEALTH_ARGS=$(python3 -c "from cloakbrowser.config import get_default_stealth_args; print(','.join(get_default_stealth_args()))")
export AGENT_BROWSER_EXECUTABLE_PATH="$BINARY_PATH"
export AGENT_BROWSER_ARGS="$STEALTH_ARGS"
```

CloakBrowser is required by default for BrowserAgent browsing.

1. Call `cloakbrowser_config` with `status`.
2. Call `cloakbrowser_config` with `configure` to verify/compute `AGENT_BROWSER_EXECUTABLE_PATH` and `AGENT_BROWSER_ARGS`.
3. Use `agent_browser_command` normally; it applies the configured environment to the subprocess.

If auto-configuration fails, use the official cloakbrowser GitHub instructions and manually export the two `AGENT_BROWSER_*` env vars on the server.
Only set `BIOINCODER_CLOAKBROWSER_REQUIRED=0` when ordinary agent-browser is explicitly acceptable.

## Learn CLI Syntax

When command syntax is uncertain, call:

```json
{"topic_args": ["-h"]}
```

For agent-browser built-in skills:

```json
{"topic_args": ["skills", "-h"]}
```

Use help for specific commands when needed:

```json
{"topic_args": ["snapshot", "-h"]}
```

## Core Workflow

Open, wait, inspect, act, wait again:

```json
{"args": ["open", "https://example.org"]}
```

```json
{"args": ["wait", "--load", "networkidle"], "timeout_seconds": 180}
```

```json
{"args": ["snapshot", "-i"]}
```

After any click, form submit, navigation, scroll, or dynamic action, wait again before reading state.

`agent_browser_command` truncates stdout/stderr by default to protect context. Use `max_output_chars` only when more output is genuinely needed.

## Essential Commands

Navigation:

```json
{"args": ["open", "https://example.org"]}
{"args": ["wait", "--load", "networkidle"]}
{"args": ["get", "url"]}
{"args": ["get", "title"]}
{"args": ["back"]}
{"args": ["forward"]}
{"args": ["reload"]}
```

Session/global options can be included in `args`:

```json
{"args": ["--session", "literature_page", "open", "https://example.org"]}
{"args": ["--headed", "open", "https://example.org"]}
```

Inspection:

```json
{"args": ["snapshot", "-i"]}
{"args": ["snapshot", "-s", "#main"]}
{"args": ["get", "text", "@e1"]}
{"args": ["get", "text", "body"]}
```

Interaction:

```json
{"args": ["click", "@e1"]}
{"args": ["dblclick", "@e1"]}
{"args": ["hover", "@e1"]}
{"args": ["fill", "@e2", "query text"]}
{"args": ["clear", "@e2"]}
{"args": ["press", "Enter"]}
{"args": ["check", "@e3"]}
{"args": ["uncheck", "@e3"]}
{"args": ["scroll", "down", "700"]}
{"args": ["upload", "@e4", "path/to/file.txt"]}
```

Capture:

```json
{"args": ["screenshot", "--full"]}
{"args": ["screenshot", "--annotate"]}
{"args": ["pdf", "artifacts/browser/page.pdf"]}
```

Small structured extraction:

```json
{"args": ["eval", "JSON.stringify(Array.from(document.querySelectorAll('a')).slice(0,20).map(a=>({text:a.innerText, href:a.href})))"]}
```

Diagnostics and state:

```json
{"args": ["logs"]}
{"args": ["network"]}
{"args": ["cookies"]}
{"args": ["storage"]}
{"args": ["tabs"]}
{"args": ["tab", "new"]}
{"args": ["state", "save", "auth.json"]}
{"args": ["state", "load", "auth.json"]}
```

Always verify exact syntax with `agent_browser_help` if unsure, because available subcommands can differ by installed agent-browser version.

## Wait Discipline

Always wait after:

- `open`, `goto`, `navigate`;
- clicking links/buttons that may change content;
- submitting forms;
- `press Enter` in search boxes;
- scroll on infinite-loading pages;
- any anti-bot or verification screen.

Preferred waits:

```json
{"args": ["wait", "--load", "networkidle"], "timeout_seconds": 180}
{"args": ["wait", "@e1"], "timeout_seconds": 120}
{"args": ["wait", "--url", "**/target*"], "timeout_seconds": 120}
{"args": ["wait", "5000"]}
```

Use fixed waits only when load-state or element waits are insufficient.

## Token-Minimal Browsing

Use the narrowest extraction that answers the objective.
This is mandatory. Browser work should use the minimum tokens and minimum context window needed to finish the task.

When only one section, table, link group, result item, or page region matters, do not read the whole page.

Prefer:

- page title and current URL;
- scoped snapshot instead of full snapshot;
- one or two targeted `get text @ref` calls;
- small `eval` extraction that filters/selects relevant content and returns structured JSON;
- screenshot/PDF artifact paths instead of pasted content.
- `max_output_chars` small enough for the current task.

Avoid:

- repeated full-body text dumps;
- raw HTML;
- copying long pages into chat;
- browsing unrelated links;
- multiple screenshots unless visual state matters.

Use JavaScript filtering with `agent-browser eval` whenever it can avoid large snapshots or full-page text dumps.

Examples:

Extract only links matching a keyword:

```json
{"args": ["eval", "JSON.stringify(Array.from(document.querySelectorAll('a')).filter(a=>/pdf|supplement|download/i.test(a.innerText+' '+a.href)).slice(0,30).map(a=>({text:a.innerText.trim(), href:a.href})))"]}
```

Extract headings and nearby text only:

```json
{"args": ["eval", "JSON.stringify(Array.from(document.querySelectorAll('h1,h2,h3')).slice(0,30).map(h=>({heading:h.innerText.trim(), next:(h.nextElementSibling&&h.nextElementSibling.innerText||'').slice(0,500)})))"]}
```

Extract table rows containing a keyword:

```json
{"args": ["eval", "JSON.stringify(Array.from(document.querySelectorAll('tr')).filter(r=>/TP53|KRAS|download/i.test(r.innerText)).slice(0,30).map(r=>r.innerText.trim()))"]}
```

Count candidates before extracting details:

```json
{"args": ["eval", "JSON.stringify({links:document.links.length, tables:document.querySelectorAll('table').length, buttons:document.querySelectorAll('button').length})"]}
```

Keep eval output short. Use `slice`, keyword filters, and field selection.

## Search/Browser Handoff

When browsing from SearchAgent results:

- Prefer URLs, DOI links, PubMed URLs, PMC URLs, arXiv URLs, or preprint URLs already returned by SearchAgent.
- If the input mentions a saved SearchAgent trace, use `list_saved_message_refs` and `read_agent_messages` to retrieve the relevant `Search_Channel` transcript.
- Do not browse a paper result without a usable URL or identifier. Ask for clarification only if no URL/identifier can be recovered from SearchAgent output.
- Keep browser work focused on the selected URL(s), not a new broad search.

## Ref Lifecycle

Element refs such as `@e1` are temporary.

After navigation, dynamic content load, or DOM-changing clicks:

1. wait;
2. run a fresh `snapshot -i`;
3. use only the new refs.

## Failure Handling

If a page is blocked, slow, or requires verification:

- wait longer;
- take an annotated screenshot if visual diagnosis is needed;
- check current URL/title;
- use `cloakbrowser_config` with `status`/`configure` if CloakBrowser env is not already active;
- report the block or access limitation instead of forcing extraction.

If agent-browser is unavailable:

- return the installation/configuration error from the tool;
- do not pretend that browsing succeeded.

## Response

Return:

- what pages were visited;
- concise findings;
- URLs used;
- artifact paths if screenshots/PDFs were created;
- limitations such as blocked access, slow load, login requirement, or anti-bot page.
