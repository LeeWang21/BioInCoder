---
name: bioincoder-browser
description: Use BioInCoder BrowserAgent with agent-browser CLI and CloakBrowser as the default browser backend for low-context web browsing, page inspection, interaction, screenshots, and targeted extraction. Use when opening websites, verifying web pages, extracting page-level evidence, or handling slow/anti-bot pages with CloakBrowser.
metadata:
  tool_type: browser
  primary_tools:
    - agent_browser_command
  intended_agent: [browser]
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
- `BIOINCODER_BROWSER_HEADLESS`: set to `1` to append `--headless,--disable-gpu` to `AGENT_BROWSER_ARGS`. Default: `1`.
- `BIOINCODER_BROWSER_INSTITUTION`: optional institution/access hint, such as `Tsinghua University`.
- `BIOINCODER_BROWSER_USERNAME`: optional username used by `browser_login_with_env`.
- `BIOINCODER_BROWSER_PASSWORD`: optional password used by `browser_login_with_env`.
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
On headless Linux servers, keep `BIOINCODER_BROWSER_HEADLESS=1`; otherwise Chromium can fail with no X display and leave the agent-browser daemon stuck.

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

## Authentication State

Use `browser_state` to save or load authenticated browser state.
State files are stored under `artifacts/browser/auth` and may contain cookies or tokens.
Treat them as sensitive.

Save state after a successful login:

```json
{"action": "save", "session_name": "library_login", "state_path": "library.json"}
```

Load state before opening protected pages:

```json
{"action": "load", "session_name": "paper_access", "state_path": "library.json"}
```

Use `browser_login_with_env` when credentials are available as environment variables.
Do not pass passwords through `agent_browser_command`.
Use `browser_auth_config` before institution/login flows to inspect configured institution, username availability, password availability, and auth state existence without exposing secrets.
Use `browser_download_artifact` to save direct PDF, supplementary file, table, archive, or dataset URLs into `artifacts/browser/downloads`.

Required inputs:

- `login_url`
- `username_selector`: CSS selector for username/email input
- `password_selector`: CSS selector for password input
- `submit_selector`: optional CSS selector for submit button

Example:

```json
{
  "login_url": "https://example.edu/login",
  "username_selector": "input[name='username']",
  "password_selector": "input[type='password']",
  "submit_selector": "button[type='submit']",
  "session_name": "library_login",
  "institution_env": "BIOINCODER_BROWSER_INSTITUTION",
  "username_env": "BIOINCODER_BROWSER_USERNAME",
  "password_env": "BIOINCODER_BROWSER_PASSWORD",
  "state_path": "library.json"
}
```

The tool does not return the password.
It fills credentials using `agent-browser eval --stdin` so the password is not placed in CLI arguments.
If selectors are unknown, browse the login page first, use a minimal snapshot/eval to identify selectors, then call `browser_login_with_env`.

## Full Text / Download Access

When the task requires article full text, PDF, supplementary files, or other protected downloads:

1. Try public, lightweight sources first:
   - article DOI landing page;
   - PubMed/PMC;
   - Europe PMC metadata or full-text XML;
   - publisher metadata;
   - explicit open-access PDF/supplement links.
2. If the page presents access choices, choose legitimate institutional/library access:
   - "Access through your institution";
   - "Institutional login";
   - "OpenAthens";
   - "Shibboleth";
   - library proxy / university login.
3. If institution selection is required, call `browser_auth_config` first and use the configured institution hint when available.
4. If an institution must be selected and neither the objective nor `browser_auth_config` provides an institution name or clear hint, do not guess. Extract a small list of visible institution options or the required search input and ask the user.
5. If the user has provided an institution name or hint, use it to search/select the matching institution, then continue with the exact target page or file.
6. Do not choose purchase-oriented options unless the user explicitly asks:
   - "Buy";
   - "Rent";
   - "Purchase PDF";
   - "Subscribe".
7. If the content is not public or a login wall appears, check for an existing auth state:

```json
{"action": "load", "session_name": "paper_access", "state_path": "library.json"}
```

8. Retry the exact target URL after loading state.
9. If no usable state exists and credentials are configured in environment variables, identify login form selectors and call `browser_login_with_env`.
10. Do not declare CAPTCHA or interactive login as a blocker only because an input exists in the DOM. Verify that the field is visible with snapshot/screenshot or computed style checks.
11. If a visible CAPTCHA, two-factor prompt, consent screen, institutional choice, manual login step, or credential problem blocks progress, stop browsing and ask the user promptly. Do not keep retrying blind browser actions.
12. Save authenticated state for reuse:

```json
{"action": "save", "session_name": "library_login", "state_path": "library.json"}
```

13. Return only the extracted findings, file path, or access limitation. Do not expose cookies, tokens, usernames, or passwords.

Do not bypass paywalls or access controls except through legitimate user-provided credentials/session state.
Do not use authenticated access for bulk downloading unless the user explicitly asks and the access terms permit it.

## Downloads

For PDFs, supplementary files, tables, archives, and dataset files:

1. Use browser commands to locate the direct file URL.
2. Prefer targeted extraction instead of full page dumps:

```json
{"args": ["eval", "JSON.stringify(Array.from(document.querySelectorAll('a')).filter(a=>/pdf|supplement|download|xlsx|csv|zip/i.test(a.innerText+' '+a.href)).slice(0,30).map(a=>({text:a.innerText.trim(), href:a.href})))"]}
```

3. Ask the user if multiple plausible files appear and the correct choice is not obvious.
4. Call `browser_download_artifact` with the direct URL:

```json
{
  "url": "https://example.org/article.pdf",
  "expected_type": "pdf",
  "referer": "https://example.org/article",
  "filename": "article.pdf"
}
```

5. Report `file_path`, `metadata_path`, source URL, and warnings.
6. If `browser_download_artifact` reports that a PDF looks like HTML, access denied, or login page content, treat the download as suspect and continue the browser/auth flow.

Do not bulk-download publisher files unless the user explicitly asks and access terms permit it.

## Core Workflow

Open, wait, inspect, act, wait again:

```json
{"args": ["--session", "task_page", "open", "https://example.org"]}
```

```json
{"args": ["--session", "task_page", "wait", "--load", "networkidle"], "timeout_seconds": 180}
```

```json
{"args": ["--session", "task_page", "snapshot", "-i"]}
```

After any click, form submit, navigation, scroll, or dynamic action, wait again before reading state.
When the task is done, close the session/browser:

```json
{"args": ["--session", "task_page", "close"]}
```

`agent_browser_command` truncates stdout/stderr by default to protect context. Use `max_output_chars` only when more output is genuinely needed.

## Essential Commands

Navigation:

```json
{"args": ["--session", "task_page", "open", "https://example.org"]}
{"args": ["--session", "task_page", "wait", "--load", "networkidle"]}
{"args": ["--session", "task_page", "get", "url"]}
{"args": ["--session", "task_page", "get", "title"]}
{"args": ["--session", "task_page", "back"]}
{"args": ["--session", "task_page", "forward"]}
{"args": ["--session", "task_page", "reload"]}
```

Session/global options can be included in `args`:

```json
{"args": ["--session", "literature_page", "open", "https://example.org"]}
{"args": ["--headed", "open", "https://example.org"]}
```

Use explicit sessions by default. Pick short names tied to the task, such as:

- `paper_page`
- `dataset_page`
- `docs_page`
- `login_page`

Avoid reusing stale sessions from unrelated tasks.

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

## Pagination / Multi-page Results

If a task involves search results, article lists, tables, dataset lists, file lists, comments, or any page where the target item may not be on the first screen/page, check for pagination before concluding.

Use lightweight detection first:

```json
{"args": ["eval", "JSON.stringify({url:location.href,title:document.title,textMatches:Array.from(document.querySelectorAll('a,button,[role=\"button\"]')).filter(e=>/next|more|load|下一页|下页|更多|后页|›|»/i.test(e.innerText||e.getAttribute('aria-label')||e.title||'')).slice(0,20).map(e=>({tag:e.tagName,text:(e.innerText||e.getAttribute('aria-label')||e.title||'').trim(),href:e.href||'',disabled:e.disabled||e.getAttribute('aria-disabled')||e.className}))})"]}
```

For result lists, extract compact page summaries:

```json
{"args": ["eval", "JSON.stringify(Array.from(document.querySelectorAll('article,li,tr,.result,.search-result')).slice(0,30).map((e,i)=>({i,text:e.innerText.trim().replace(/\\s+/g,' ').slice(0,300),href:e.querySelector('a')?.href||''})))"]}
```

Continue to the next page or click "load more" when:

- the task asks for all/comprehensive results;
- the requested item is not found on the current page;
- the page reports more total results than currently visible;
- relevant downloads or supplementary files are likely split across pages/tabs.

After each pagination action, wait before extracting:

```json
{"args": ["wait", "--load", "networkidle"], "timeout_seconds": 120}
```

Stop pagination when:

- the requested item or enough evidence has been found;
- the next/load-more control is disabled or absent;
- several pages are irrelevant to the task;
- a task-specific page limit from the user has been reached.

Do not dump every page. Return compact per-page findings and mention the page range inspected. If only page 1 was inspected, say that explicitly in Notes / Limitations.

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

## Session Cleanup

Always close the browser/session when:

- the browser task is complete;
- the page is stuck and recovery requires a fresh session;
- authentication or sensitive content was opened;
- the agent will switch to an unrelated website.

Use:

```json
{"args": ["--session", "task_page", "close"]}
```

If several sessions may be open, inspect sessions first:

```json
{"args": ["session", "list"]}
```

Then close the relevant session.

## Stuck Browser Daemon

`The browser daemon seems stuck` usually means agent-browser's background daemon or controlled browser stopped responding.

Common causes:

- previous page is still loading or blocked by network/anti-bot checks;
- a command is waiting on a load state that never resolves;
- stale refs were used after navigation;
- the browser session accumulated too much state;
- CloakBrowser binary/env changed while daemon was already running;
- too many sessions/pages were left open;
- a prior command timed out and left the daemon in a bad state.

Recovery pattern:

1. Try a lightweight status check:

```json
{"args": ["--session", "task_page", "get", "url"], "timeout_seconds": 30}
```

2. Try a short wait:

```json
{"args": ["--session", "task_page", "wait", "3000"], "timeout_seconds": 30}
```

3. If still stuck, close the affected session/browser:

```json
{"args": ["--session", "task_page", "close"], "timeout_seconds": 30}
```

4. Start a fresh session and continue only from the minimum needed URL/context.

Do not keep sending heavy snapshots or full-page extraction commands to a stuck session.

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

Ask the user promptly whenever browser progress needs the user's choice, confirmation, manual action, credential-related input, or other interaction that should not be guessed.
Keep the question concrete and include the current URL plus the smallest useful set of visible options or actions.
If asking is unavailable or fails, return a `need_user_input` section for BioInCoder.

## Failure Budget

Be persistent, but do not retry forever.

For the same URL, page, interface, or repeated failure mode, allow several reasonable recovery attempts. As a guideline:

- 5 attempts is enough for most repeated timeout, anti-bot, stale-ref, or daemon-stuck failures;
- 10 attempts is the upper bound for important pages when different recovery strategies are being tried;
- do not exceed this range unless the user explicitly requested exhaustive browser retries.

Reasonable recovery strategies include:

- wait longer;
- use a fresh session;
- close and reopen the session;
- switch from full page browse to targeted `eval`;
- use a lighter endpoint such as Europe PMC XML, DOI metadata, PubMed, or publisher metadata;
- try a direct PDF/supplement link if already known.

When the failure budget is reached:

- stop browsing that target;
- summarize what was tried;
- report the failure pattern;
- preserve partial findings;
- suggest the next best route;
- return a response to BioInCoder.

Do not continue sending heavy snapshots, repeated opens, or full-page extraction commands after repeated failure.

## Response

Return:

- what pages were visited;
- concise findings;
- URLs used;
- artifact paths if screenshots/PDFs were created;
- limitations such as blocked access, slow load, login requirement, or anti-bot page.
