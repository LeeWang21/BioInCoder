from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import BaseTool, ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from Tool_utils import tool_error_command, tool_error_response


AGENT_BROWSER_BIN = os.environ.get("BIOINCODER_AGENT_BROWSER_BIN", "agent-browser")
CLOAKBROWSER_BIN = os.environ.get("BIOINCODER_CLOAKBROWSER_BIN", "cloakbrowser")
CLOAKBROWSER_REQUIRED = os.environ.get("BIOINCODER_CLOAKBROWSER_REQUIRED", "1") != "0"
CLOAKBROWSER_AUTO_CONFIG = os.environ.get("BIOINCODER_CLOAKBROWSER_AUTO_CONFIG", "1") != "0"
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


def _positive_int(name: str, value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"`{name}` must be a positive integer.")
    return min(value, maximum)


def _run_cli(args: list[str], timeout_seconds: int, env_update: dict[str, str] | None = None) -> dict[str, Any]:
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


def _resolve_cloakbrowser_env() -> dict[str, str]:
    global _CLOAKBROWSER_ENV_CACHE

    executable_path = os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH")
    browser_args = os.environ.get("AGENT_BROWSER_ARGS")
    if executable_path and browser_args:
        return {
            "AGENT_BROWSER_EXECUTABLE_PATH": executable_path,
            "AGENT_BROWSER_ARGS": browser_args,
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
        "AGENT_BROWSER_ARGS": stealth_args,
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


class BrowserBrowse(BaseTool):
    name: str = "browser_browse"
    description: str = (
        "Call BrowserAgent for web browsing with agent-browser CLI using CloakBrowser by default. "
        "Use when academic APIs are insufficient, a page must be opened/read, or interactive browser actions are needed. "
        "The full browser trace is saved in Browser_Channel."
    )
    args_schema: type[BaseModel] = BrowserBrowseInput

    def _run(self, objective: str, runtime: ToolRuntime):
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
                    "- Prefer targeted snapshots, text extraction, and URLs over full-page dumps.\n"
                    "- When only part of a page matters, use agent-browser eval or scoped snapshots to filter before extracting text.\n"
                    "- After opening a page or any navigation/action, wait patiently with agent-browser wait before reading state.\n"
                    "- If CLI syntax is uncertain, inspect agent-browser help/skills first.\n"
                    "- CloakBrowser is the default browser backend; use cloakbrowser_config status/configure if configuration is uncertain.\n"
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
            return tool_error_command(
                exc,
                tool_call_id=runtime.tool_call_id,
                hint="BrowserAgent failed. Retry browser_browse with a narrower objective or inspect saved messages.",
            )
