from __future__ import annotations

import os
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import BaseTool, ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from Tool_utils import is_graph_interrupt, tool_error_command, tool_error_response


AGENT_BROWSER_BIN = os.environ.get("BIOINCODER_AGENT_BROWSER_BIN", "agent-browser")
CLOAKBROWSER_BIN = os.environ.get("BIOINCODER_CLOAKBROWSER_BIN", "cloakbrowser")
CLOAKBROWSER_REQUIRED = os.environ.get("BIOINCODER_CLOAKBROWSER_REQUIRED", "1") != "0"
CLOAKBROWSER_AUTO_CONFIG = os.environ.get("BIOINCODER_CLOAKBROWSER_AUTO_CONFIG", "1") != "0"
BROWSER_HEADLESS = os.environ.get("BIOINCODER_BROWSER_HEADLESS", "1") != "0"
HEADLESS_AGENT_BROWSER_ARGS = ["--headless", "--disable-gpu"]
BROWSER_ARTIFACT_DIR = Path.cwd() / "artifacts" / "browser"
_CLOAKBROWSER_ENV_CACHE: dict[str, str] | None = None

ALLOWED_AGENT_BROWSER_COMMANDS = {
    "back",
    "clear",
    "open",
    "goto",
    "navigate",
    "close",
    "cookies",
    "snapshot",
    "click",
    "dblclick",
    "hover",
    "fill",
    "type",
    "select",
    "check",
    "uncheck",
    "press",
    "drag",
    "drop",
    "scroll",
    "get",
    "wait",
    "screenshot",
    "pdf",
    "diff",
    "eval",
    "find",
    "forward",
    "logs",
    "network",
    "reload",
    "state",
    "session",
    "storage",
    "tab",
    "tabs",
    "upload",
    "highlight",
    "record",
    "skills",
}


def _extract_session_name(args: list[str]) -> str | None:
    for index, arg in enumerate(args[:-1]):
        if arg == "--session":
            return args[index + 1]
    return None


def _positive_int(name: str, value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"`{name}` must be a positive integer.")
    return min(value, maximum)


def _run_cli(
    args: list[str],
    timeout_seconds: int,
    env_update: dict[str, str] | None = None,
    input_text: str | None = None,
) -> dict[str, Any]:
    started_at = time.time()
    env = os.environ.copy()
    if env_update:
        env.update(env_update)
    proc = subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        env=env,
        input=input_text,
    )
    return {
        "ok": proc.returncode == 0,
        "command": args,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_seconds": round(time.time() - started_at, 3),
    }


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n... [truncated]", True


def _find_agent_browser_subcommand(args: list[str]) -> str | None:
    for arg in args:
        if arg in ALLOWED_AGENT_BROWSER_COMMANDS:
            return arg
    return None


def _agent_browser_prefix() -> list[str]:
    return [AGENT_BROWSER_BIN]


def _browser_auth_path(path: str | None) -> Path:
    root = (BROWSER_ARTIFACT_DIR / "auth").resolve()
    root.mkdir(parents=True, exist_ok=True)
    if path is None or not path.strip():
        candidate = root / "browser_state.json"
    else:
        raw_path = Path(path)
        if raw_path.is_absolute():
            candidate = raw_path.resolve()
        else:
            candidate = (root / raw_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Browser auth state path must stay inside artifacts/browser/auth.")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _merge_agent_browser_args(browser_args: str) -> str:
    parts = [part.strip() for part in browser_args.split(",") if part.strip()]
    if BROWSER_HEADLESS:
        existing = set(parts)
        for arg in HEADLESS_AGENT_BROWSER_ARGS:
            if arg not in existing:
                parts.append(arg)
                existing.add(arg)
    return ",".join(parts)


def _resolve_cloakbrowser_env() -> dict[str, str]:
    global _CLOAKBROWSER_ENV_CACHE

    executable_path = os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH")
    browser_args = os.environ.get("AGENT_BROWSER_ARGS")
    if executable_path and browser_args:
        return {
            "AGENT_BROWSER_EXECUTABLE_PATH": executable_path,
            "AGENT_BROWSER_ARGS": _merge_agent_browser_args(browser_args),
        }

    if not CLOAKBROWSER_AUTO_CONFIG:
        if CLOAKBROWSER_REQUIRED:
            raise RuntimeError(
                "CloakBrowser is required but BIOINCODER_CLOAKBROWSER_AUTO_CONFIG=0 "
                "and AGENT_BROWSER_EXECUTABLE_PATH/AGENT_BROWSER_ARGS are not both set."
            )
        return {}

    if _CLOAKBROWSER_ENV_CACHE is not None:
        return dict(_CLOAKBROWSER_ENV_CACHE)

    try:
        binary = subprocess.check_output(
            [
                "python3",
                "-c",
                "from cloakbrowser.download import ensure_binary; print(ensure_binary())",
            ],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=120,
        ).strip()
        stealth_args = subprocess.check_output(
            [
                "python3",
                "-c",
                "from cloakbrowser.config import get_default_stealth_args; print(','.join(get_default_stealth_args()))",
            ],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=120,
        ).strip()
    except Exception as exc:
        if CLOAKBROWSER_REQUIRED:
            raise RuntimeError(
                "CloakBrowser is required but automatic configuration failed. "
                "Install cloakbrowser or manually set AGENT_BROWSER_EXECUTABLE_PATH and AGENT_BROWSER_ARGS."
            ) from exc
        return {}

    _CLOAKBROWSER_ENV_CACHE = {
        "AGENT_BROWSER_EXECUTABLE_PATH": binary,
        "AGENT_BROWSER_ARGS": _merge_agent_browser_args(stealth_args),
    }
    return dict(_CLOAKBROWSER_ENV_CACHE)


class AgentBrowserCommandInput(BaseModel):
    args: list[str] = Field(
        ...,
        description=(
            "agent-browser CLI arguments without the binary name, e.g. "
            "['open', 'https://example.org'] or ['wait', '--load', 'networkidle']."
        ),
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Command timeout. Defaults to 120 seconds and is capped at 600 seconds.",
    )
    max_output_chars: int | None = Field(
        default=None,
        description="Maximum stdout/stderr characters returned. Defaults to 12000 and is capped at 50000.",
    )


class AgentBrowserCommand(BaseTool):
    name: str = "agent_browser_command"
    description: str = (
        "Run one controlled agent-browser CLI command. "
        "CloakBrowser is applied by default through AGENT_BROWSER_EXECUTABLE_PATH and AGENT_BROWSER_ARGS. "
        "Pass arguments as a JSON list, not a shell string. "
        "Always use agent_browser_help or the browser skill when command syntax is uncertain. "
        "After open/click/fill/press/scroll/navigation-like actions, run an explicit wait command before reading the page."
    )
    args_schema: type[BaseModel] = AgentBrowserCommandInput

    def _run(
        self,
        args: list[str],
        timeout_seconds: int | None = None,
        max_output_chars: int | None = None,
    ) -> dict[str, Any]:
        try:
            if not args:
                raise ValueError("`args` must contain at least one agent-browser subcommand.")
            command = _find_agent_browser_subcommand(args)
            if command not in ALLOWED_AGENT_BROWSER_COMMANDS:
                raise ValueError(
                    f"No allowed agent-browser subcommand was found in args. "
                    f"Allowed: {sorted(ALLOWED_AGENT_BROWSER_COMMANDS)}"
                )
            timeout = _positive_int("timeout_seconds", timeout_seconds, default=120, maximum=600)
            output_limit = _positive_int(
                "max_output_chars",
                max_output_chars,
                default=12000,
                maximum=50000,
            )
            env_update = _resolve_cloakbrowser_env()
            out = _run_cli(_agent_browser_prefix() + args, timeout, env_update=env_update)
            session_name = _extract_session_name(args)
            if session_name:
                out["session_name"] = session_name
            out["cloakbrowser_env_applied"] = bool(env_update)
            stdout, stdout_truncated = _truncate_text(out["stdout"], output_limit)
            stderr, stderr_truncated = _truncate_text(out["stderr"], output_limit)
            out["stdout"] = stdout
            out["stderr"] = stderr
            out["stdout_truncated"] = stdout_truncated
            out["stderr_truncated"] = stderr_truncated
            out["output_limit_chars"] = output_limit
            return out
        except Exception as exc:
            return tool_error_response(
                exc,
                hint=(
                    "Check that agent-browser and cloakbrowser are installed on the server, "
                    "or manually set AGENT_BROWSER_EXECUTABLE_PATH and AGENT_BROWSER_ARGS. "
                    "Use agent_browser_help for CLI usage."
                ),
            )


class AgentBrowserHelpInput(BaseModel):
    topic_args: list[str] = Field(
        default_factory=list,
        description=(
            "Optional help topic args after agent-browser, e.g. ['skills', '-h'], ['snapshot', '-h'], or ['-h']."
        ),
    )


class AgentBrowserHelp(BaseTool):
    name: str = "agent_browser_help"
    description: str = (
        "Read agent-browser CLI help. Use before browser work when syntax is uncertain. "
        "For built-in agent-browser skills, call with topic_args=['skills','-h']."
    )
    args_schema: type[BaseModel] = AgentBrowserHelpInput

    def _run(self, topic_args: list[str] | None = None) -> dict[str, Any]:
        try:
            args = topic_args or ["-h"]
            return _run_cli([AGENT_BROWSER_BIN] + args, timeout_seconds=30)
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="agent-browser help failed. Confirm agent-browser is installed and available in PATH.",
            )


class CloakBrowserConfigInput(BaseModel):
    action: Literal["status", "configure", "help"] = Field(
        ...,
        description="Inspect or configure cloakbrowser environment used by agent-browser.",
    )


class CloakBrowserConfig(BaseTool):
    name: str = "cloakbrowser_config"
    description: str = (
        "Inspect or configure cloakbrowser for agent-browser browsing. "
        "CloakBrowser's agent-browser integration uses AGENT_BROWSER_EXECUTABLE_PATH and AGENT_BROWSER_ARGS; "
        "agent-browser launches CloakBrowser itself rather than connecting to an existing CDP browser."
    )
    args_schema: type[BaseModel] = CloakBrowserConfigInput

    def _run(self, action: str) -> dict[str, Any]:
        try:
            BROWSER_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

            if action == "status":
                configured_env = {
                    "AGENT_BROWSER_EXECUTABLE_PATH": os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH"),
                    "AGENT_BROWSER_ARGS": os.environ.get("AGENT_BROWSER_ARGS"),
                }
                return {
                    "ok": True,
                    "integration_mode": "agent-browser launches CloakBrowser via env vars",
                    "cloakbrowser_required": CLOAKBROWSER_REQUIRED,
                    "auto_config_enabled": CLOAKBROWSER_AUTO_CONFIG,
                    "agent_browser_executable_path_configured": bool(configured_env["AGENT_BROWSER_EXECUTABLE_PATH"]),
                    "agent_browser_args_configured": bool(configured_env["AGENT_BROWSER_ARGS"]),
                    "cached_env": bool(_CLOAKBROWSER_ENV_CACHE),
                }

            if action == "help":
                return _run_cli([CLOAKBROWSER_BIN, "-h"], timeout_seconds=30)

            if action == "configure":
                env_update = _resolve_cloakbrowser_env()
                if not env_update:
                    return {
                        "ok": False,
                        "error_type": "ConfigurationRequired",
                        "error": "CloakBrowser auto configuration is disabled or unavailable.",
                        "hint": (
                            "Install cloakbrowser on the server, set BIOINCODER_CLOAKBROWSER_AUTO_CONFIG=1, "
                            "or manually export AGENT_BROWSER_EXECUTABLE_PATH and AGENT_BROWSER_ARGS. "
                            "Set BIOINCODER_CLOAKBROWSER_REQUIRED=0 only if ordinary agent-browser is acceptable."
                        ),
                    }
                return {
                    "ok": True,
                    "integration_mode": "agent-browser launches CloakBrowser via env vars",
                    "env": {
                        "AGENT_BROWSER_EXECUTABLE_PATH": env_update["AGENT_BROWSER_EXECUTABLE_PATH"],
                        "AGENT_BROWSER_ARGS": env_update["AGENT_BROWSER_ARGS"],
                    },
                }

            raise ValueError(f"Unsupported action: {action}")
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="cloakbrowser config failed. Check server installation and cloakbrowser/agent-browser env vars.",
            )


class BrowserCleanupInput(BaseModel):
    session_name: str | None = Field(
        default=None,
        description="Optional agent-browser session name to close. If omitted, runs agent-browser close.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Cleanup timeout. Defaults to 30 seconds and is capped at 120 seconds.",
    )


class BrowserCleanup(BaseTool):
    name: str = "browser_cleanup"
    description: str = (
        "Close an agent-browser session/browser with CloakBrowser env applied. "
        "Use at the end of browser work or when a session is stuck. This is a gentle cleanup, not pkill."
    )
    args_schema: type[BaseModel] = BrowserCleanupInput

    def _run(
        self,
        session_name: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        try:
            timeout = _positive_int("timeout_seconds", timeout_seconds, default=30, maximum=120)
            args = _agent_browser_prefix()
            if session_name:
                args.extend(["--session", session_name])
            args.append("close")
            out = _run_cli(args, timeout_seconds=timeout, env_update=_resolve_cloakbrowser_env())
            out["session_name"] = session_name
            out["cleanup"] = "gentle"
            return out
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="Gentle browser cleanup failed. Manual cleanup may require agent-browser close or pkill on the server.",
            )


class BrowserStateInput(BaseModel):
    action: Literal["save", "load"] = Field(
        ...,
        description="Save or load an agent-browser authentication/session state file.",
    )
    session_name: str = Field(
        ...,
        description="agent-browser session name to save from or load into.",
    )
    state_path: str | None = Field(
        default=None,
        description="Relative path under artifacts/browser/auth. Defaults to browser_state.json.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="State command timeout. Defaults to 60 seconds and is capped at 180 seconds.",
    )


class BrowserState(BaseTool):
    name: str = "browser_state"
    description: str = (
        "Save or load agent-browser login/session state. "
        "Use this to reuse authenticated browser sessions without exposing passwords. "
        "State files can contain cookies/tokens and are stored under artifacts/browser/auth."
    )
    args_schema: type[BaseModel] = BrowserStateInput

    def _run(
        self,
        action: str,
        session_name: str,
        state_path: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        try:
            if action not in {"save", "load"}:
                raise ValueError("`action` must be 'save' or 'load'.")
            timeout = _positive_int("timeout_seconds", timeout_seconds, default=60, maximum=180)
            path = _browser_auth_path(state_path)
            args = _agent_browser_prefix() + [
                "--session",
                session_name,
                "state",
                action,
                str(path),
            ]
            out = _run_cli(args, timeout_seconds=timeout, env_update=_resolve_cloakbrowser_env())
            out["session_name"] = session_name
            out["state_path"] = str(path)
            out["state_file_sensitive"] = True
            return out
        except Exception as exc:
            return tool_error_response(
                exc,
                hint=(
                    "browser_state failed. Confirm agent-browser supports `state save/load` "
                    "and keep auth state paths under artifacts/browser/auth."
                ),
            )


class BrowserLoginWithEnvInput(BaseModel):
    login_url: str = Field(
        ...,
        description="Login page URL.",
    )
    username_selector: str = Field(
        ...,
        description="CSS selector for the username/email input.",
    )
    password_selector: str = Field(
        ...,
        description="CSS selector for the password input.",
    )
    submit_selector: str | None = Field(
        default=None,
        description="Optional CSS selector for submit button. If omitted, presses Enter on the password field.",
    )
    session_name: str = Field(
        default="browser_login",
        description="agent-browser session name used for login.",
    )
    username_env: str = Field(
        default="BIOINCODER_BROWSER_USERNAME",
        description="Environment variable containing the username. Its value is never returned.",
    )
    password_env: str = Field(
        default="BIOINCODER_BROWSER_PASSWORD",
        description="Environment variable containing the password. Its value is never returned.",
    )
    state_path: str | None = Field(
        default=None,
        description="Relative path under artifacts/browser/auth to save login state. Defaults to browser_state.json.",
    )
    wait_after_login_ms: int | None = Field(
        default=None,
        description="Milliseconds to wait after submit. Defaults to 5000 and is capped at 60000.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Timeout for each browser command. Defaults to 120 seconds and is capped at 600 seconds.",
    )


class BrowserLoginWithEnv(BaseTool):
    name: str = "browser_login_with_env"
    description: str = (
        "Log in using username/password stored in environment variables, then save browser state. "
        "Requires CSS selectors for the username and password fields. "
        "Does not return the username or password and avoids putting the password in CLI arguments."
    )
    args_schema: type[BaseModel] = BrowserLoginWithEnvInput

    def _run(
        self,
        login_url: str,
        username_selector: str,
        password_selector: str,
        submit_selector: str | None = None,
        session_name: str = "browser_login",
        username_env: str = "BIOINCODER_BROWSER_USERNAME",
        password_env: str = "BIOINCODER_BROWSER_PASSWORD",
        state_path: str | None = None,
        wait_after_login_ms: int | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        try:
            username = os.environ.get(username_env)
            password = os.environ.get(password_env)
            if not username:
                raise ValueError(f"Username environment variable is not set: {username_env}")
            if not password:
                raise ValueError(f"Password environment variable is not set: {password_env}")

            timeout = _positive_int("timeout_seconds", timeout_seconds, default=120, maximum=600)
            wait_ms = _positive_int(
                "wait_after_login_ms",
                wait_after_login_ms,
                default=5000,
                maximum=60000,
            )
            auth_path = _browser_auth_path(state_path)
            env_update = _resolve_cloakbrowser_env()
            prefix = _agent_browser_prefix() + ["--session", session_name]

            steps: list[dict[str, Any]] = []
            steps.append(
                _run_cli(prefix + ["open", login_url], timeout_seconds=timeout, env_update=env_update)
            )
            steps.append(
                _run_cli(prefix + ["wait", "--load", "networkidle"], timeout_seconds=timeout, env_update=env_update)
            )

            submit_js = (
                "const submit = document.querySelector(SUBMIT_SELECTOR);\n"
                "if (!submit) throw new Error('Submit selector not found: ' + SUBMIT_SELECTOR);\n"
                "submit.click();\n"
                if submit_selector
                else (
                    "passwordEl.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));\n"
                    "passwordEl.form && passwordEl.form.requestSubmit && passwordEl.form.requestSubmit();\n"
                )
            )
            script = f"""
const USERNAME_SELECTOR = {json.dumps(username_selector)};
const PASSWORD_SELECTOR = {json.dumps(password_selector)};
const SUBMIT_SELECTOR = {json.dumps(submit_selector)};
const usernameEl = document.querySelector(USERNAME_SELECTOR);
const passwordEl = document.querySelector(PASSWORD_SELECTOR);
if (!usernameEl) throw new Error('Username selector not found: ' + USERNAME_SELECTOR);
if (!passwordEl) throw new Error('Password selector not found: ' + PASSWORD_SELECTOR);
function setValue(el, value) {{
  el.focus();
  el.value = value;
  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
  el.dispatchEvent(new Event('change', {{ bubbles: true }}));
}}
setValue(usernameEl, {json.dumps(username)});
setValue(passwordEl, {json.dumps(password)});
{submit_js}
JSON.stringify({{ ok: true, submitted: true }});
"""
            eval_out = _run_cli(
                prefix + ["eval", "--stdin"],
                timeout_seconds=timeout,
                env_update=env_update,
                input_text=script,
            )
            eval_out["command"] = prefix + ["eval", "--stdin"]
            eval_out["secret_redacted"] = True
            steps.append(eval_out)
            steps.append(
                _run_cli(prefix + ["wait", str(wait_ms)], timeout_seconds=timeout, env_update=env_update)
            )
            steps.append(
                _run_cli(
                    prefix + ["state", "save", str(auth_path)],
                    timeout_seconds=timeout,
                    env_update=env_update,
                )
            )

            ok = all(step.get("ok") for step in steps)
            return {
                "ok": ok,
                "session_name": session_name,
                "login_url": login_url,
                "username_env": username_env,
                "password_env": password_env,
                "password_redacted": True,
                "state_path": str(auth_path),
                "state_file_sensitive": True,
                "steps": [
                    {
                        "ok": step.get("ok"),
                        "command": step.get("command"),
                        "returncode": step.get("returncode"),
                        "stdout": step.get("stdout"),
                        "stderr": step.get("stderr"),
                        "elapsed_seconds": step.get("elapsed_seconds"),
                        "secret_redacted": step.get("secret_redacted", False),
                    }
                    for step in steps
                ],
            }
        except Exception as exc:
            return tool_error_response(
                exc,
                hint=(
                    "browser_login_with_env failed. Confirm env vars are set, CSS selectors are correct, "
                    "and the login page is accessible with agent-browser/CloakBrowser."
                ),
            )


class BrowserBrowseInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    objective: str = Field(
        ...,
        description=(
            "The browser task objective. Include target URL, what to inspect or extract, constraints, "
            "and whether screenshots/artifacts are needed."
        ),
    )
    runtime: ToolRuntime
    cleanup_session_name: str | None = Field(
        default=None,
        description=(
            "Optional agent-browser session name to close in a finally-style cleanup after BrowserAgent returns. "
            "If omitted, browser_browse runs a gentle global agent-browser close."
        ),
    )


class BrowserBrowse(BaseTool):
    name: str = "browser_browse"
    description: str = (
        "Call BrowserAgent for web browsing with agent-browser CLI using CloakBrowser by default. "
        "Use when academic APIs are insufficient, a page must be opened/read, or interactive browser actions are needed. "
        "The full browser trace is saved in Browser_Channel."
    )
    args_schema: type[BaseModel] = BrowserBrowseInput

    def _run(
        self,
        objective: str,
        runtime: ToolRuntime,
        cleanup_session_name: str | None = None,
    ):
        cleanup_result = None
        try:
            from AgentConfigSetup import multi_agent_runtime

            coder_msgs = runtime.state.get("messages", [])
            coder_msgs_sanitization = coder_msgs
            if coder_msgs_sanitization and getattr(coder_msgs_sanitization[-1], "tool_calls", None):
                coder_msgs_sanitization = coder_msgs_sanitization[:-1]

            browser_instruction = HumanMessage(
                content=(
                    "Perform the following browser task with agent-browser CLI using CloakBrowser by default.\n\n"
                    f"# Objective\n{objective}\n\n"
                    "# Operating constraints\n"
                    "- Use the smallest number of browser commands and the smallest context needed.\n"
                    "- Use an explicit agent-browser --session name for the task.\n"
                    "- Prefer targeted snapshots, text extraction, and URLs over full-page dumps.\n"
                    "- When only part of a page matters, use agent-browser eval or scoped snapshots to filter before extracting text.\n"
                    "- After opening a page or any navigation/action, wait patiently with agent-browser wait before reading state.\n"
                    "- If CLI syntax is uncertain, inspect agent-browser help/skills first.\n"
                    "- CloakBrowser is the default browser backend; use cloakbrowser_config status/configure if configuration is uncertain.\n"
                    "- If full text, PDF, or supplementary files are blocked, try public metadata/OA routes first. If the page offers access choices, prefer legitimate institutional/library access such as Access through your institution, Institutional login, OpenAthens, Shibboleth, or library proxy; do not choose Buy, Rent, Purchase PDF, or Subscribe unless the user explicitly asks. If institution selection is required and no institution name/hint was provided, extract a small list of visible options or required input and return need_user_input instead of guessing. Then load saved auth state or use env-based login if legitimate credentials are configured.\n"
                    "- Close the browser/session with agent-browser close when the task is done or the session gets stuck.\n"
                    "- Do not ask the user directly. If blocked, return a need_user_input section for BioInCoder.\n"
                    "- Return concise findings and cite URLs or artifact paths. Do not paste large page contents."
                )
            )

            request_id = runtime.tool_call_id
            browser_config = multi_agent_runtime.make_child_config(
                parent_config=getattr(runtime, "config", None),
                agent_name="browser",
                request_id=request_id,
            )
            browser_state, message_ref = multi_agent_runtime.invoke_agent(
                agent_name="browser",
                graph_input={"messages": coder_msgs_sanitization + [browser_instruction]},
                request_id=request_id,
                config=browser_config,
            )

            messages = multi_agent_runtime.extract_messages(browser_state)
            final_content = ""
            if messages:
                final_content = str(getattr(messages[-1], "content", messages[-1]))

            if message_ref is not None:
                final_content = (
                    f"{final_content}\n\n"
                    "# Saved subagent messages\n"
                    f"{message_ref.to_tool_hint()}"
                )

            return Command(
                update={
                    "messages": [
                        ToolMessage(content=final_content, tool_call_id=runtime.tool_call_id)
                    ]
                }
            )
        except Exception as exc:
            if is_graph_interrupt(exc):
                raise
            return tool_error_command(
                exc,
                tool_call_id=runtime.tool_call_id,
                hint="BrowserAgent failed. Retry browser_browse with a narrower objective or inspect saved messages.",
            )
        finally:
            try:
                cleanup_result = BrowserCleanup()._run(
                    session_name=cleanup_session_name,
                    timeout_seconds=30,
                )
            except Exception:
                cleanup_result = None
