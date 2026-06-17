from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import BaseTool, ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from Tool_utils import is_graph_interrupt, tool_error_command, tool_error_response


MARKITDOWN_BIN = os.environ.get("BIOINCODER_MARKITDOWN_BIN", "markitdown")
READ_ARTIFACT_DIR = Path.cwd() / "artifacts" / "read"
ALLOWED_MARKITDOWN_EXTRA_ARGS = {
    "-x",
    "--use-plugins",
    "--keep-data-uris",
    "--list-plugins",
    "--version",
    "-h",
    "--help",
}
ALLOWED_PIPE_COMMANDS = {"grep", "head", "tail", "sed", "wc", "rg", "cut", "sort", "uniq"}
ALLOWED_GREP_FLAGS = {
    "-i",
    "--ignore-case",
    "-n",
    "--line-number",
    "-E",
    "--extended-regexp",
    "-F",
    "--fixed-strings",
}
GREP_FLAGS_WITH_VALUE = {"-A", "--after-context", "-B", "--before-context", "-C", "--context", "-m", "--max-count", "-e", "--regexp"}
ALLOWED_RG_FLAGS = {
    "-i",
    "--ignore-case",
    "-n",
    "--line-number",
    "-N",
    "--no-line-number",
    "-F",
    "--fixed-strings",
    "-e",
    "--regexp",
}
RG_FLAGS_WITH_VALUE = {"-A", "--after-context", "-B", "--before-context", "-C", "--context", "-m", "--max-count", "-e", "--regexp"}
ALLOWED_WC_FLAGS = {"-l", "-w", "-c", "-m"}
ALLOWED_CUT_FLAGS_WITH_VALUE = {"-c", "--characters", "-f", "--fields", "-d", "--delimiter"}
ALLOWED_SORT_FLAGS = {"-n", "--numeric-sort", "-r", "--reverse", "-u", "--unique"}
ALLOWED_UNIQ_FLAGS = {"-c", "--count", "-d", "--repeated", "-u", "--unique", "-i", "--ignore-case"}


def _positive_int(name: str, value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"`{name}` must be a positive integer.")
    return min(value, maximum)


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n... [truncated]", True


def _safe_output_path(output_name: str | None, source: str) -> Path:
    READ_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if output_name and output_name.strip():
        raw_name = Path(output_name).name
    else:
        source_name = Path(source.split("?", 1)[0]).name or "document"
        raw_name = f"{Path(source_name).stem or 'document'}.md"
    raw_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    if not raw_name:
        raw_name = "document.md"
    if not Path(raw_name).suffix:
        raw_name += ".md"
    stamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    candidate = (READ_ARTIFACT_DIR / f"{stamp}_{raw_name}").resolve()
    root = READ_ARTIFACT_DIR.resolve()
    if root not in candidate.parents:
        raise ValueError("Read output path must stay inside artifacts/read.")
    return candidate


def _validate_source(source: str) -> None:
    if not source or not source.strip():
        raise ValueError("`source` is required.")
    if source.startswith(("http://", "https://")):
        return
    path = Path(source).expanduser()
    if not path.exists():
        raise ValueError(f"Source file does not exist: {source}")
    if not path.is_file():
        raise ValueError(f"Source path is not a file: {source}")


def _validate_extra_args(extra_args: list[str] | None) -> list[str]:
    args = list(extra_args or [])
    for arg in args:
        if arg not in ALLOWED_MARKITDOWN_EXTRA_ARGS:
            raise ValueError(
                f"Unsupported markitdown extra arg: {arg}. "
                f"Allowed: {sorted(ALLOWED_MARKITDOWN_EXTRA_ARGS)}"
            )
    return args


def _validate_pipe_commands(pipe_commands: list[list[str]] | None) -> list[list[str]]:
    commands = [list(command) for command in (pipe_commands or [])]
    if len(commands) > 4:
        raise ValueError("At most 4 pipe commands are allowed.")

    validated: list[list[str]] = []
    for command in commands:
        if not command:
            raise ValueError("Pipe command cannot be empty.")
        name = command[0]
        if name not in ALLOWED_PIPE_COMMANDS:
            raise ValueError(f"Unsupported pipe command: {name}. Allowed: {sorted(ALLOWED_PIPE_COMMANDS)}")
        for token in command:
            if "\x00" in token or "\n" in token or "\r" in token:
                raise ValueError("Pipe command tokens cannot contain control characters.")
            if len(token) > 500:
                raise ValueError("Pipe command token is too long.")

        if name in {"head", "tail"}:
            if len(command) != 3 or command[1] != "-n":
                raise ValueError(f"{name} only supports the form: [{name!r}, '-n', '<positive integer>'].")
            _positive_int(f"{name} -n", int(command[2]), default=100, maximum=2000)

        if name == "grep":
            pattern_count = 0
            index = 1
            while index < len(command):
                token = command[index]
                if token in ALLOWED_GREP_FLAGS:
                    index += 1
                    continue
                if token in GREP_FLAGS_WITH_VALUE:
                    if index + 1 >= len(command):
                        raise ValueError(f"grep flag requires a value: {token}")
                    if token != "-e" and token != "--regexp":
                        if token in {"-A", "--after-context", "-B", "--before-context", "-C", "--context", "-m", "--max-count"}:
                            _positive_int(f"grep {token}", int(command[index + 1]), default=1, maximum=2000)
                    else:
                        pattern_count += 1
                    index += 2
                    continue
                if token.startswith("-"):
                    raise ValueError(f"Unsupported grep flag: {token}")
                pattern_count += 1
                index += 1
            if pattern_count != 1:
                raise ValueError("grep pipe commands must include exactly one pattern and no file path arguments.")

        if name == "rg":
            pattern_count = 0
            index = 1
            while index < len(command):
                token = command[index]
                if token in ALLOWED_RG_FLAGS and token not in RG_FLAGS_WITH_VALUE:
                    index += 1
                    continue
                if token in RG_FLAGS_WITH_VALUE:
                    if index + 1 >= len(command):
                        raise ValueError(f"rg flag requires a value: {token}")
                    if token in {"-A", "--after-context", "-B", "--before-context", "-C", "--context", "-m", "--max-count"}:
                        _positive_int(f"rg {token}", int(command[index + 1]), default=1, maximum=2000)
                    else:
                        pattern_count += 1
                    index += 2
                    continue
                if token.startswith("-"):
                    raise ValueError(f"Unsupported rg flag: {token}")
                pattern_count += 1
                index += 1
            if pattern_count != 1:
                raise ValueError("rg pipe commands must include exactly one pattern and no file path arguments.")
            if command[-1] != "-":
                command.append("-")

        if name == "sed":
            if len(command) != 3 or command[1] != "-n":
                raise ValueError("sed only supports the form: ['sed', '-n', '<start>,<end>p'].")
            match = re.fullmatch(r"(\d+),(\d+)p", command[2])
            if not match:
                raise ValueError("sed range must look like '120,180p'.")
            start, end = int(match.group(1)), int(match.group(2))
            if start <= 0 or end < start or end - start > 2000:
                raise ValueError("sed range must be positive and span at most 2000 lines.")

        if name == "wc":
            if not (2 <= len(command) <= 5):
                raise ValueError("wc supports only flags such as -l, -w, -c, -m and no file path arguments.")
            for token in command[1:]:
                if token not in ALLOWED_WC_FLAGS:
                    raise ValueError(f"Unsupported wc flag: {token}")

        if name == "cut":
            index = 1
            saw_selector = False
            while index < len(command):
                token = command[index]
                if token in ALLOWED_CUT_FLAGS_WITH_VALUE:
                    if index + 1 >= len(command):
                        raise ValueError(f"cut flag requires a value: {token}")
                    if token in {"-c", "--characters", "-f", "--fields"}:
                        if not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", command[index + 1]):
                            raise ValueError(f"Unsupported cut range: {command[index + 1]}")
                        saw_selector = True
                    if token in {"-d", "--delimiter"} and len(command[index + 1]) > 10:
                        raise ValueError("cut delimiter is too long.")
                    index += 2
                    continue
                raise ValueError(f"Unsupported cut argument: {token}")
            if not saw_selector:
                raise ValueError("cut requires -c/--characters or -f/--fields.")

        if name == "sort":
            if len(command) > 5:
                raise ValueError("sort supports at most 4 flags and no file path arguments.")
            for token in command[1:]:
                if token not in ALLOWED_SORT_FLAGS:
                    raise ValueError(f"Unsupported sort flag: {token}")

        if name == "uniq":
            if len(command) > 5:
                raise ValueError("uniq supports at most 4 flags and no file path arguments.")
            for token in command[1:]:
                if token not in ALLOWED_UNIQ_FLAGS:
                    raise ValueError(f"Unsupported uniq flag: {token}")

        validated.append(command)
    return validated


def _run_markitdown_pipeline(command: list[str], pipe_commands: list[list[str]], timeout: int) -> tuple[int, str, str]:
    if not pipe_commands:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""

    processes: list[subprocess.Popen] = []
    previous_stdout = None
    try:
        first = subprocess.Popen(
            command,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(first)
        previous_stdout = first.stdout

        for pipe_command in pipe_commands:
            proc = subprocess.Popen(
                pipe_command,
                text=True,
                stdin=previous_stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if previous_stdout is not None:
                previous_stdout.close()
            processes.append(proc)
            previous_stdout = proc.stdout

        stdout, stderr = processes[-1].communicate(timeout=timeout)
        stderr_parts = [stderr or ""]
        for proc in processes[:-1]:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            if proc.stderr is not None:
                stderr_parts.append(proc.stderr.read() or "")
        returncode = processes[-1].returncode
        for proc in processes[:-1]:
            if proc.returncode not in {0, None} and returncode == 0:
                returncode = proc.returncode
        return returncode or 0, stdout or "", "\n".join(part for part in stderr_parts if part)
    except Exception:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
        raise


class MarkItDownCommandInput(BaseModel):
    source: str = Field(
        ...,
        description="Local file path or http(s) URL to convert with markitdown.",
    )
    extra_args: list[str] | None = Field(
        default=None,
        description=(
            "Optional safe markitdown flags. Supported: -x, --use-plugins, "
            "--keep-data-uris, --list-plugins, --version, -h, --help."
        ),
    )
    pipe_commands: list[list[str]] | None = Field(
        default=None,
        description=(
            "Optional safe stdout pipeline after markitdown, expressed as command arrays without shell. "
            "Allowed commands: grep, head, tail, sed, wc, rg, cut, sort, uniq. "
            "Example: [['grep','-n','-i','RAM'], ['head','-n','80']]."
        ),
    )
    save_output: bool = Field(
        default=True,
        description=(
            "Save converted markdown to artifacts/read. If pipe_commands are used, saves the piped output; "
            "otherwise saves the full MarkItDown stdout."
        ),
    )
    output_name: str | None = Field(
        default=None,
        description="Optional output markdown filename under artifacts/read.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Command timeout. Defaults to 180 seconds and is capped at 1200 seconds.",
    )
    max_output_chars: int | None = Field(
        default=None,
        description="Maximum returned stdout characters. Defaults to 12000 and is capped at 50000.",
    )


class MarkItDownCommand(BaseTool):
    name: str = "markitdown_command"
    description: str = (
        "Convert a document with the markitdown CLI and return agent-readable Markdown stdout. "
        "Use for quick reading of PDFs, Word, Excel, PowerPoint, HTML, CSV/JSON/XML, and related files. "
        "Supports safe stdout pipelines with grep/head/tail/sed/wc/rg/cut/sort/uniq, "
        "output truncation, and saved Markdown under artifacts/read."
    )
    args_schema: type[BaseModel] = MarkItDownCommandInput

    def _run(
        self,
        source: str,
        extra_args: list[str] | None = None,
        pipe_commands: list[list[str]] | None = None,
        save_output: bool = True,
        output_name: str | None = None,
        timeout_seconds: int | None = None,
        max_output_chars: int | None = None,
    ) -> dict[str, Any]:
        try:
            _validate_source(source)
            args = _validate_extra_args(extra_args)
            pipes = _validate_pipe_commands(pipe_commands)
            timeout = _positive_int("timeout_seconds", timeout_seconds, default=180, maximum=1200)
            max_chars = _positive_int("max_output_chars", max_output_chars, default=12000, maximum=50000)

            command = [MARKITDOWN_BIN] + args + [source]
            started_at = _dt.datetime.utcnow()
            returncode, markdown, stderr_text = _run_markitdown_pipeline(command, pipes, timeout)
            output_path = None
            if save_output and markdown:
                output_path = _safe_output_path(output_name, source)
                output_path.write_text(markdown, encoding="utf-8")

            line_stats = {"stdout_lines": len(markdown.splitlines())}
            returned, truncated = _truncate_text(markdown, max_chars)
            stderr, stderr_truncated = _truncate_text(stderr_text, 4000)
            return {
                "ok": returncode == 0,
                "command": command,
                "pipe_commands": pipes,
                "returncode": returncode,
                "source": source,
                "output_path": str(output_path) if output_path else None,
                "stdout": returned,
                "stdout_truncated": truncated,
                "stderr": stderr,
                "stderr_truncated": stderr_truncated,
                "line_stats": line_stats,
                "elapsed_seconds": round((_dt.datetime.utcnow() - started_at).total_seconds(), 3),
            }
        except Exception as exc:
            return tool_error_response(
                exc,
                hint=(
                    "markitdown_command failed. Confirm markitdown is installed and the source path/URL is valid. "
                    "Use pipe_commands and max_output_chars to keep outputs small."
                ),
            )


class ReadArtifactInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_brief: str = Field(
        ...,
        description=(
            "Self-contained handoff brief for ReadAgent. Subagents do not receive the full BioInCoder conversation. "
            "Include: Overall Goal, Current Subtask, Relevant Context, Inputs such as file_path/metadata_path/source URL/message refs, "
            "Scope Boundary, Required Output, Stop Condition, and Handoff. Specify target content, keywords, fields, tables, sheets, "
            "sections, snippets to extract, output format, limitations, and a reminder not to browse the web or search literature."
        ),
    )
    file_path: str = Field(
        ...,
        description="Local file path to read.",
    )
    runtime: ToolRuntime


class ReadArtifact(BaseTool):
    name: str = "read_artifact"
    description: str = (
        "Call ReadAgent to inspect and read a local document artifact. "
        "Use for PDFs, Word, Excel, PowerPoint, HTML, CSV/TSV, JSON/XML, and downloaded supplementary files. "
        "The full ReadAgent trace is saved in Read_Channel."
    )
    args_schema: type[BaseModel] = ReadArtifactInput

    def _run(
        self,
        file_path: str,
        runtime: ToolRuntime,
        task_brief: str,
    ):
        try:
            from AgentConfigSetup import multi_agent_runtime

            read_instruction = HumanMessage(
                content=(
                    "Perform the following local document reading task.\n\n"
                    f"# Task brief\n{task_brief}\n\n"
                    f"# File\n{file_path}\n\n"
                    "# Operating constraints\n"
                    "- Use markitdown_command for quick document-to-Markdown conversion and targeted text extraction.\n"
                    "- Stay within the task brief. Do not browse the web, search literature, or perform computational analysis beyond reading the provided file.\n"
                    "- Keep returned context small with pipe_commands and max_output_chars.\n"
                    "- For large files or narrow objectives, prefer safe stdout pipelines such as [['grep','-i','keyword'], ['head','-n','120']] before returning text.\n"
                    "- Save converted Markdown when useful and report output_path.\n"
                    "- For Excel/PowerPoint/Word/PDF, do not dump the whole file unless the user explicitly asks.\n"
                    "- If the task brief mentions a specific keyword, table, sheet, section, or figure, search/filter for that target first.\n"
                    "- Return concise findings with file path, converted artifact path, and any limitations."
                )
            )

            request_id = runtime.tool_call_id
            read_config = multi_agent_runtime.make_child_config(
                parent_config=getattr(runtime, "config", None),
                agent_name="reader",
                request_id=request_id,
            )
            read_state, message_ref = multi_agent_runtime.invoke_agent(
                agent_name="reader",
                graph_input={"messages": [read_instruction]},
                request_id=request_id,
                config=read_config,
            )

            messages = multi_agent_runtime.extract_messages(read_state)
            final_content = ""
            if messages:
                final_content = str(getattr(messages[-1], "content", messages[-1]))

            if message_ref is not None:
                final_content = (
                    f"{final_content}\n\n"
                    "# Saved subagent messages\n"
                    f"{message_ref.to_tool_hint()}"
                )

            return Command(update={"messages": [ToolMessage(content=final_content, tool_call_id=runtime.tool_call_id)]})
        except Exception as exc:
            if is_graph_interrupt(exc):
                raise
            return tool_error_command(
                exc,
                runtime.tool_call_id,
                hint="ReadAgent failed. Retry read_artifact with a clearer, narrower task_brief or inspect saved messages.",
            )
