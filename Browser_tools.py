from __future__ import annotations

import datetime as _dt
import hashlib
import mimetypes
import os
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
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
DOWNLOAD_DIR = BROWSER_ARTIFACT_DIR / "downloads"
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


def _safe_download_path(filename: str | None, url: str, content_type: str | None) -> Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if filename and filename.strip():
        raw_name = Path(filename).name
    else:
        parsed = urllib.parse.urlparse(url)
        raw_name = Path(urllib.parse.unquote(parsed.path)).name
        if not raw_name:
            ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".bin"
            raw_name = f"download{ext}"
    raw_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    if not raw_name:
        raw_name = "download.bin"
    stem = Path(raw_name).stem[:120] or "download"
    suffix = Path(raw_name).suffix[:20]
    stamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    candidate = (DOWNLOAD_DIR / f"{stamp}_{stem}{suffix}").resolve()
    root = DOWNLOAD_DIR.resolve()
    if root not in candidate.parents:
        raise ValueError("Download path must stay inside artifacts/browser/downloads.")
    return candidate


def _looks_like_html(path: Path, content_type: str | None) -> bool:
    if content_type and "html" in content_type.lower():
        return True
    try:
        head = path.read_bytes()[:512].lower()
    except Exception:
        return False
    return b"<html" in head or b"<!doctype html" in head


def _looks_like_pdf(path: Path, content_type: str | None) -> bool:
    if content_type and "pdf" in content_type.lower():
        return True
    try:
        return path.read_bytes()[:5] == b"%PDF-"
    except Exception:
        return False


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


class BrowserAuthConfigInput(BaseModel):
    username_env: str = Field(
        default="BIOINCODER_BROWSER_USERNAME",
        description="Environment variable containing the username.",
    )
    password_env: str = Field(
        default="BIOINCODER_BROWSER_PASSWORD",
        description="Environment variable containing the password.",
    )
    institution_env: str = Field(
        default="BIOINCODER_BROWSER_INSTITUTION",
        description="Environment variable containing the institution name or access hint.",
    )
    state_path: str | None = Field(
        default=None,
        description="Relative browser auth state path to inspect under artifacts/browser/auth.",
    )


class BrowserAuthConfig(BaseTool):
    name: str = "browser_auth_config"
    description: str = (
        "Inspect browser authentication configuration without exposing secrets. "
        "Reports whether username/password env vars are set, the configured institution hint, "
        "and whether the requested browser auth state file exists."
    )
    args_schema: type[BaseModel] = BrowserAuthConfigInput

    def _run(
        self,
        username_env: str = "BIOINCODER_BROWSER_USERNAME",
        password_env: str = "BIOINCODER_BROWSER_PASSWORD",
        institution_env: str = "BIOINCODER_BROWSER_INSTITUTION",
        state_path: str | None = None,
    ) -> dict[str, Any]:
        try:
            auth_path = _browser_auth_path(state_path)
            institution = os.environ.get(institution_env)
            return {
                "ok": True,
                "username_env": username_env,
                "username_configured": bool(os.environ.get(username_env)),
                "password_env": password_env,
                "password_configured": bool(os.environ.get(password_env)),
                "password_redacted": True,
                "institution_env": institution_env,
                "institution": institution if institution else None,
                "institution_configured": bool(institution),
                "state_path": str(auth_path),
                "state_file_exists": auth_path.exists(),
                "state_file_sensitive": True,
            }
        except Exception as exc:
            return tool_error_response(
                exc,
                hint="browser_auth_config failed. Keep auth state paths under artifacts/browser/auth.",
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
    institution_env: str = Field(
        default="BIOINCODER_BROWSER_INSTITUTION",
        description="Optional environment variable containing the institution name or access hint.",
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
        institution_env: str = "BIOINCODER_BROWSER_INSTITUTION",
        state_path: str | None = None,
        wait_after_login_ms: int | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        try:
            username = os.environ.get(username_env)
            password = os.environ.get(password_env)
            institution = os.environ.get(institution_env)
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
            if not eval_out.get("ok"):
                return {
                    "ok": False,
                    "session_name": session_name,
                    "login_url": login_url,
                    "username_env": username_env,
                    "password_env": password_env,
                    "institution_env": institution_env,
                    "institution": institution,
                    "password_redacted": True,
                    "state_path": str(auth_path),
                    "state_file_sensitive": True,
                    "state_saved": False,
                    "hint": "Login form submission failed. Do not treat the auth state as logged in.",
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
            steps.append(
                _run_cli(prefix + ["wait", str(wait_ms)], timeout_seconds=timeout, env_update=env_update)
            )
            status_script = """
function visible(el) {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
}
const visiblePasswordInputs = Array.from(document.querySelectorAll('input[type="password"]')).filter(visible).length;
const visibleCaptchaInputs = Array.from(document.querySelectorAll('input,textarea'))
  .filter(visible)
  .filter(el => /captcha|验证码|校验码|i_code|verify/i.test([el.id, el.name, el.placeholder, el.getAttribute('aria-label')].join(' ')))
  .map(el => ({id: el.id, name: el.name, placeholder: el.placeholder}));
const bodyText = document.body ? document.body.innerText.slice(0, 5000) : '';
const errorLike = /验证码|校验码|captcha|错误|失败|无效|invalid|incorrect|failed/i.test(bodyText);
JSON.stringify({
  url: location.href,
  title: document.title,
  visiblePasswordInputs,
  visibleCaptchaInputs,
  errorLike
});
"""
            status_out = _run_cli(
                prefix + ["eval", status_script],
                timeout_seconds=timeout,
                env_update=env_update,
            )
            steps.append(status_out)
            login_status: dict[str, Any] = {}
            if status_out.get("ok") and status_out.get("stdout"):
                try:
                    login_status = json.loads(json.loads(status_out["stdout"]))
                except Exception:
                    login_status = {}
            if (
                login_status.get("visiblePasswordInputs", 0) > 0
                or login_status.get("visibleCaptchaInputs")
                or login_status.get("errorLike")
            ):
                return {
                    "ok": False,
                    "session_name": session_name,
                    "login_url": login_url,
                    "username_env": username_env,
                    "password_env": password_env,
                    "institution_env": institution_env,
                    "institution": institution,
                    "password_redacted": True,
                    "state_path": str(auth_path),
                    "state_file_sensitive": True,
                    "state_saved": False,
                    "login_status": login_status,
                    "hint": (
                        "Login did not appear complete after submission. "
                        "Visible password/captcha/error indicators remain, so auth state was not saved."
                    ),
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
                "institution_env": institution_env,
                "institution": institution,
                "password_redacted": True,
                "state_path": str(auth_path),
                "state_file_sensitive": True,
                "state_saved": ok,
                "login_status": login_status,
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


class BrowserDownloadArtifactInput(BaseModel):
    url: str = Field(
        ...,
        description="Direct URL to download, such as a PDF, supplementary table, archive, or dataset file.",
    )
    filename: str | None = Field(
        default=None,
        description="Optional safe output filename. The file is always saved under artifacts/browser/downloads.",
    )
    expected_type: Literal["any", "pdf", "table", "archive", "text"] = Field(
        default="any",
        description="Expected artifact type used for validation warnings.",
    )
    referer: str | None = Field(
        default=None,
        description="Optional Referer header, usually the article or landing page URL.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Download timeout. Defaults to 180 seconds and is capped at 900 seconds.",
    )
    max_bytes: int | None = Field(
        default=None,
        description="Maximum bytes to download. Defaults to 100 MB and is capped at 500 MB.",
    )


class BrowserDownloadArtifact(BaseTool):
    name: str = "browser_download_artifact"
    description: str = (
        "Download a direct browser-discovered artifact URL into artifacts/browser/downloads. "
        "Use for PDFs, supplementary files, tables, archives, or dataset files after BrowserAgent has found the URL. "
        "Returns file path and validation metadata, and warns when a downloaded PDF looks like an HTML access page."
    )
    args_schema: type[BaseModel] = BrowserDownloadArtifactInput

    def _run(
        self,
        url: str,
        filename: str | None = None,
        expected_type: str = "any",
        referer: str | None = None,
        timeout_seconds: int | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("`url` must be an http(s) URL.")
            timeout = _positive_int("timeout_seconds", timeout_seconds, default=180, maximum=900)
            byte_limit = _positive_int("max_bytes", max_bytes, default=100 * 1024 * 1024, maximum=500 * 1024 * 1024)

            headers = {
                "User-Agent": "Mozilla/5.0 BioInCoder BrowserAgent",
                "Accept": "*/*",
            }
            if referer:
                headers["Referer"] = referer
            request = urllib.request.Request(url, headers=headers)

            started_at = time.time()
            sha256 = hashlib.sha256()
            bytes_written = 0
            status_code: int | None = None
            final_url = url
            content_type: str | None = None
            content_length: int | None = None

            with urllib.request.urlopen(request, timeout=timeout) as response:
                status_code = getattr(response, "status", None)
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type")
                length_header = response.headers.get("Content-Length")
                if length_header and length_header.isdigit():
                    content_length = int(length_header)
                    if content_length > byte_limit:
                        raise ValueError(
                            f"Remote file is too large: {content_length} bytes exceeds max_bytes={byte_limit}."
                        )
                output_path = _safe_download_path(filename, final_url, content_type)
                with output_path.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        bytes_written += len(chunk)
                        if bytes_written > byte_limit:
                            raise ValueError(f"Download exceeded max_bytes={byte_limit}.")
                        sha256.update(chunk)
                        handle.write(chunk)

            is_html = _looks_like_html(output_path, content_type)
            is_pdf = _looks_like_pdf(output_path, content_type)
            warnings: list[str] = []
            if expected_type == "pdf" and not is_pdf:
                warnings.append("Expected a PDF, but the downloaded file does not look like a PDF.")
            if is_html:
                warnings.append("Downloaded content looks like HTML; it may be a login, access-denied, or error page.")
            if bytes_written == 0:
                warnings.append("Downloaded file is empty.")

            metadata = {
                "source_url": url,
                "final_url": final_url,
                "referer": referer,
                "status_code": status_code,
                "content_type": content_type,
                "content_length": content_length,
                "bytes": bytes_written,
                "sha256": sha256.hexdigest(),
                "expected_type": expected_type,
                "looks_like_pdf": is_pdf,
                "looks_like_html": is_html,
                "warnings": warnings,
                "downloaded_at_utc": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "elapsed_seconds": round(time.time() - started_at, 3),
            }
            metadata_path = output_path.with_suffix(output_path.suffix + ".metadata.json")
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "ok": not warnings,
                "file_path": str(output_path),
                "metadata_path": str(metadata_path),
                **metadata,
            }
        except urllib.error.HTTPError as exc:
            return tool_error_response(
                exc,
                hint=f"Download failed with HTTP status {exc.code}. The URL may require browser login or a different link.",
            )
        except Exception as exc:
            return tool_error_response(
                exc,
                hint=(
                    "browser_download_artifact failed. Use BrowserAgent to find a direct PDF/supplement URL first, "
                    "and avoid bulk downloads unless explicitly requested."
                ),
            )


class BrowserBrowseInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_brief: str = Field(
        ...,
        description=(
            "Self-contained handoff brief for BrowserAgent. Subagents do not receive the full BioInCoder conversation. "
            "Include: Overall Goal, Current Subtask, Relevant Context, Inputs such as exact target URL(s)/DOIs/PMIDs/message refs, "
            "Scope Boundary, Required Output, Stop Condition, and Handoff. Specify what page-level evidence or downloads are needed, "
            "allowed/forbidden actions, access/login constraints, user interaction requirements, session cleanup expectations, "
            "and which downloaded file paths or artifact metadata should be handed to ReadAgent."
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
        runtime: ToolRuntime,
        task_brief: str,
        cleanup_session_name: str | None = None,
    ):
        cleanup_result = None
        try:
            from AgentConfigSetup import multi_agent_runtime

            browser_instruction = HumanMessage(
                content=(
                    "BrowserAgent delegated task.\n\n"
                    f"# Task brief\n{task_brief}\n\n"
                    "# Message instruction\n"
                    "Use the task brief as the binding scope for this browser work. "
                    "Return concise page findings, source URLs, downloaded artifact paths/metadata paths, "
                    "access state, blockers, user-input needs, and limitations needed for BioInCoder handoff. "
                    "Do not perform local document reading after download."
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
                graph_input={"messages": [browser_instruction]},
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
                hint="BrowserAgent failed. Retry browser_browse with a clearer, narrower task_brief or inspect saved messages.",
            )
        finally:
            try:
                cleanup_result = BrowserCleanup()._run(
                    session_name=cleanup_session_name,
                    timeout_seconds=30,
                )
            except Exception:
                cleanup_result = None
