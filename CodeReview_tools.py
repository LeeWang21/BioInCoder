from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import BaseTool, ToolRuntime
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from Tool_utils import is_graph_interrupt, tool_error_command, tool_error_response


CODE_REVIEW_ROOT = Path.cwd() / "artifacts" / "code_review"
DEFAULT_MAX_CHARS = 12000
REVIEWABLE_SUFFIXES = {
    ".ipynb",
    ".py",
    ".r",
    ".R",
    ".sh",
    ".bash",
    ".zsh",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
}
REVIEWABLE_FILENAMES = {
    "Snakefile",
    "nextflow.config",
    "Dockerfile",
    "Makefile",
}
RUN_DENYLIST = {
    "rm",
    "mv",
    "git",
    "pip",
    "pip3",
    "conda",
    "mamba",
    "brew",
    "curl",
    "wget",
    "scp",
    "rsync",
    "ssh",
    "sudo",
    "chmod",
    "chown",
}

try:
    from jupytercode_tool import NotebookRegistry
except Exception:  # pragma: no cover - handled at notebook execution time
    NotebookRegistry = None  # type: ignore[assignment]

REVIEW_JUPYTER_REGISTRY = NotebookRegistry(user_id="CodeReviewer", session_id="code_review") if NotebookRegistry else None


def _now_review_id() -> str:
    return f"review-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}"


def _review_dir(review_id: str) -> Path:
    if not review_id or not review_id.startswith("review-"):
        raise ValueError("review_id must be provided and start with 'review-'.")
    root = CODE_REVIEW_ROOT.resolve()
    path = (root / review_id).resolve()
    if path != root and root not in path.parents:
        raise ValueError("review_id resolves outside artifacts/code_review.")
    return path


def _workspace_dir(review_id: str) -> Path:
    return _review_dir(review_id) / "workspace"


def _logs_dir(review_id: str) -> Path:
    return _review_dir(review_id) / "logs"


def _outputs_dir(review_id: str) -> Path:
    return _review_dir(review_id) / "outputs"


def _ensure_review_dirs(review_id: str) -> dict[str, Path]:
    review = _review_dir(review_id)
    workspace = _workspace_dir(review_id)
    logs = _logs_dir(review_id)
    outputs = _outputs_dir(review_id)
    for path in (review, workspace, logs, outputs):
        path.mkdir(parents=True, exist_ok=True)
    return {"review": review, "workspace": workspace, "logs": logs, "outputs": outputs}


def _safe_workspace_path(review_id: str, path: str | None = None, *, must_exist: bool = False) -> Path:
    workspace = _workspace_dir(review_id).resolve()
    raw = Path(path or ".")
    candidate = raw if raw.is_absolute() else workspace / raw
    candidate = candidate.resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise ValueError("Path must stay inside the review workspace.")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Workspace path does not exist: {candidate}")
    return candidate


def _relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _truncate(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n... [truncated]", True


def _is_reviewable_file(path: Path) -> bool:
    return path.is_file() and (path.suffix in REVIEWABLE_SUFFIXES or path.name in REVIEWABLE_FILENAMES)


def _copy_target_to_workspace(source: Path, workspace: Path) -> dict[str, Any]:
    source = source.resolve()
    if not source.exists():
        return {"source": str(source), "status": "missing"}

    destination = workspace / source.name
    if destination.exists():
        stamp = time.strftime("%H%M%S")
        destination = workspace / f"{source.stem}_{stamp}{source.suffix}"

    if source.is_dir():
        ignore = shutil.ignore_patterns(
            ".git",
            ".venv",
            "venv",
            "env",
            "__pycache__",
            ".ipynb_checkpoints",
            "artifacts",
            "node_modules",
        )
        shutil.copytree(source, destination, ignore=ignore)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    return {
        "source": str(source),
        "workspace_path": _relative_to(destination, workspace),
        "status": "copied",
        "is_dir": destination.is_dir(),
    }


def _list_files(root: Path, max_files: int = 200) -> tuple[list[dict[str, Any]], bool]:
    if root.is_file():
        return [
            {
                "path": root.name,
                "type": "file",
                "size_bytes": root.stat().st_size,
            }
        ], False

    files: list[dict[str, Any]] = []
    truncated = False
    base = root.resolve()
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            truncated = True
            break
        rel = _relative_to(path, base)
        files.append(
            {
                "path": rel,
                "type": "dir" if path.is_dir() else "file",
                "size_bytes": path.stat().st_size if path.is_file() else None,
            }
        )
    return files, truncated


def _read_text(path: Path, max_chars: int) -> dict[str, Any]:
    if path.suffix == ".ipynb":
        return _notebook_read_summary(path, max_chars=max_chars)

    text = path.read_text(encoding="utf-8", errors="replace")
    truncated_text, truncated = _truncate(text, max_chars=max_chars)
    return {
        "ok": True,
        "path": str(path),
        "kind": "text",
        "truncated": truncated,
        "content": truncated_text,
    }


def _load_notebook_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "cells" not in data:
        raise ValueError("File is not a valid notebook JSON object.")
    return data


def _cell_source(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return str(source or "")


def _outputs_preview(cell: dict[str, Any], max_chars: int = 1200) -> tuple[str, bool, bool]:
    parts = []
    has_error = False
    for output in cell.get("outputs", []) or []:
        output_type = output.get("output_type")
        if output_type == "error":
            has_error = True
            traceback = output.get("traceback") or []
            parts.append("\n".join(str(line) for line in traceback[-8:]))
        elif output_type == "stream":
            parts.append(str(output.get("text", "")))
        elif output_type in {"display_data", "execute_result"}:
            data = output.get("data") or {}
            if "text/plain" in data:
                parts.append(str(data["text/plain"]))
            elif "image/png" in data:
                parts.append("[image/png output]")
            elif "text/html" in data:
                parts.append("[text/html output]")
            else:
                parts.append("[rich output]")
    text, truncated = _truncate("\n".join(parts).strip(), max_chars=max_chars)
    return text, truncated, has_error


def _heading_level(source: str) -> int | None:
    stripped = source.lstrip()
    if not stripped.startswith("#"):
        return None
    count = 0
    for char in stripped:
        if char == "#":
            count += 1
        else:
            break
    if count and len(stripped) > count and stripped[count].isspace():
        return count
    return None


def _select_notebook_cells(
    cells: list[dict[str, Any]],
    *,
    section: str | None = None,
    query: str | None = None,
    cell_start: int | None = None,
    cell_end: int | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    indexed = list(enumerate(cells))
    if section:
        lowered = section.lower()
        start = None
        level = None
        for index, cell in indexed:
            if cell.get("cell_type") != "markdown":
                continue
            source = _cell_source(cell)
            if lowered in source.lower():
                start = index
                level = _heading_level(source) or 999
                break
        if start is None:
            return []
        end = len(cells) - 1
        for index in range(start + 1, len(cells)):
            cell = cells[index]
            if cell.get("cell_type") == "markdown":
                next_level = _heading_level(_cell_source(cell))
                if next_level is not None and next_level <= level:
                    end = index - 1
                    break
        indexed = [(index, cell) for index, cell in indexed if start <= index <= end]

    if query:
        lowered = query.lower()
        indexed = [(index, cell) for index, cell in indexed if lowered in _cell_source(cell).lower()]

    if cell_start is not None:
        indexed = [(index, cell) for index, cell in indexed if index >= cell_start]
    if cell_end is not None:
        indexed = [(index, cell) for index, cell in indexed if index <= cell_end]

    return indexed


def _notebook_cells_payload(
    cells: list[tuple[int, dict[str, Any]]],
    *,
    include_source: bool,
    max_chars: int,
) -> tuple[list[dict[str, Any]], bool]:
    payload = []
    remaining = max_chars
    truncated = False
    for index, cell in cells:
        source = _cell_source(cell)
        output_preview, output_truncated, has_error = _outputs_preview(cell)
        item: dict[str, Any] = {
            "index": index,
            "cell_type": cell.get("cell_type"),
            "execution_count": cell.get("execution_count"),
            "source_preview": source[:500] + ("...[truncated]" if len(source) > 500 else ""),
            "has_error_output": has_error,
            "output_preview": output_preview,
            "output_truncated": output_truncated,
        }
        if include_source:
            if remaining <= 0:
                item["source"] = "[omitted: max_chars exceeded]"
                truncated = True
            else:
                source_text, source_truncated = _truncate(source, max_chars=remaining)
                item["source"] = source_text
                remaining -= len(source_text)
                truncated = truncated or source_truncated
        payload.append(item)
    return payload, truncated


def _notebook_read_summary(path: Path, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    nb = _load_notebook_json(path)
    cells = nb.get("cells") or []
    selected = list(enumerate(cells))
    payload, truncated = _notebook_cells_payload(selected, include_source=False, max_chars=max_chars)
    code_cells = [cell for cell in cells if cell.get("cell_type") == "code"]
    error_cells = [item["index"] for item in payload if item["has_error_output"]]
    unexecuted = [
        index
        for index, cell in enumerate(cells)
        if cell.get("cell_type") == "code" and cell.get("execution_count") is None and _cell_source(cell).strip()
    ]
    return {
        "ok": True,
        "path": str(path),
        "kind": "notebook_summary",
        "num_cells": len(cells),
        "num_code_cells": len(code_cells),
        "error_cell_indices": error_cells,
        "unexecuted_code_cell_indices": unexecuted,
        "truncated": truncated,
        "cells": payload,
    }


def _notebook_info(path: Path) -> dict[str, Any]:
    nb = _load_notebook_json(path)
    metadata = nb.get("metadata") or {}
    kernelspec = metadata.get("kernelspec") or {}
    language_info = metadata.get("language_info") or {}
    metadata_kernel = kernelspec.get("name")
    language = language_info.get("name")

    available_kernels: list[str] = []
    kernel_error = None
    try:
        from jupyter_client.kernelspec import KernelSpecManager

        available_kernels = sorted(KernelSpecManager().find_kernel_specs().keys())
    except Exception as exc:  # pragma: no cover - depends on runtime environment
        kernel_error = f"{type(exc).__name__}: {exc}"

    recommended = metadata_kernel

    return {
        "ok": True,
        "path": str(path),
        "metadata_kernel": metadata_kernel,
        "display_name": kernelspec.get("display_name"),
        "language": language,
        "available_kernels": available_kernels,
        "kernel_lookup_error": kernel_error,
        "recommended_kernel": recommended,
        "kernel_available": recommended in available_kernels if available_kernels and recommended else None,
        "kernel_policy": "metadata_kernelspec_required_for_execution",
    }


def _notebook_read(
    path: Path,
    *,
    section: str | None,
    query: str | None,
    cell_start: int | None,
    cell_end: int | None,
    include_source: bool,
    max_chars: int,
) -> dict[str, Any]:
    nb = _load_notebook_json(path)
    selected = _select_notebook_cells(
        nb.get("cells") or [],
        section=section,
        query=query,
        cell_start=cell_start,
        cell_end=cell_end,
    )
    payload, truncated = _notebook_cells_payload(selected, include_source=include_source, max_chars=max_chars)
    return {
        "ok": True,
        "path": str(path),
        "selected_count": len(payload),
        "selection": {
            "section": section,
            "query": query,
            "cell_start": cell_start,
            "cell_end": cell_end,
        },
        "truncated": truncated,
        "cells": payload,
    }


def _review_notebook_name(review_id: str, path: Path) -> str:
    safe_name = "".join(char if char.isalnum() else "_" for char in path.stem)[:80]
    return f"{review_id}_{safe_name}"


def _review_jupyter_registry(review_id: str):
    if REVIEW_JUPYTER_REGISTRY is None:
        raise RuntimeError("jupytercode_tool.NotebookRegistry is unavailable in this runtime.")
    REVIEW_JUPYTER_REGISTRY.configure(
        user_id="CodeReviewer",
        session_id=review_id,
        overwrite=True,
    )
    return REVIEW_JUPYTER_REGISTRY


def _notebook_execute(
    review_id: str,
    path: Path,
    *,
    kernel_name: str | None,
    cell_start: int | None,
    cell_end: int | None,
    timeout_seconds: int,
    restart_kernel: bool,
) -> dict[str, Any]:
    info = _notebook_info(path)
    metadata_kernel = info.get("metadata_kernel")
    if not metadata_kernel:
        return {
            "ok": False,
            "error_type": "KernelSelectionError",
            "error": "Notebook metadata.kernelspec.name is missing; review execution requires the kernel recorded in the notebook.",
            "notebook_info": info,
        }
    if kernel_name is not None and kernel_name != metadata_kernel:
        return {
            "ok": False,
            "error_type": "KernelSelectionError",
            "error": (
                f"Requested kernel '{kernel_name}' does not match notebook metadata kernel "
                f"'{metadata_kernel}'. Review execution must use the notebook-recorded kernel."
            ),
            "notebook_info": info,
        }
    if info.get("available_kernels") and metadata_kernel not in info["available_kernels"]:
        return {
            "ok": False,
            "error_type": "KernelSelectionError",
            "error": (
                f"Notebook metadata kernel '{metadata_kernel}' is not available in this runtime. "
                "Execution was not attempted to avoid changing reproducibility conditions."
            ),
            "notebook_info": info,
        }
    selected_kernel = metadata_kernel

    nb_json = _load_notebook_json(path)
    cells = nb_json.get("cells") or []
    start = 0 if cell_start is None else cell_start
    end = len(cells) - 1 if cell_end is None else cell_end
    if start < 0 or end >= len(cells) or start > end:
        raise ValueError(f"Invalid cell range {start}..{end} for notebook with {len(cells)} cells.")

    registry = _review_jupyter_registry(review_id)
    name = _review_notebook_name(review_id, path)
    session = registry.use_notebook(
        name=name,
        notebook_path=str(path),
        kernel_name=str(selected_kernel),
    )
    if restart_kernel:
        session.restart_kernel()

    started = time.monotonic()
    executed = []
    failed = None
    try:
        for index in range(start, end + 1):
            cell = session.nb.cells[index]
            if cell.get("cell_type") != "code":
                continue
            result = session.execute_cell(index=index, timeout_seconds=timeout_seconds)
            executed.append(
                {
                    "index": index,
                    "ok": result.get("ok"),
                    "execution_count": result.get("execution_count"),
                    "error": result.get("error"),
                    "timed_out": result.get("timed_out", False),
                    "output_preview": result.get("output_preview", ""),
                }
            )
            if not result.get("ok"):
                failed = executed[-1]
                break
    finally:
        session.save()

    return {
        "ok": failed is None,
        "path": str(path),
        "review_notebook_session": name,
        "kernel_name": selected_kernel,
        "executed_notebook": str(path),
        "executed_cells": executed,
        "failed_cell": failed,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _notebook_shutdown(review_id: str, path: str | None = None) -> dict[str, Any]:
    registry = _review_jupyter_registry(review_id)
    if path:
        notebook_path = _safe_workspace_path(review_id, path, must_exist=True)
        name = _review_notebook_name(review_id, notebook_path)
        if name in registry.nb_collections:
            registry.shutdown_notebook(name)
            return {"ok": True, "shutdown": [name]}
        return {"ok": True, "shutdown": [], "message": f"No review notebook session named {name}."}

    names = registry.list_sessions()
    for name in list(names):
        if name.startswith(f"{review_id}_"):
            registry.shutdown_notebook(name)
    return {"ok": True, "shutdown": [name for name in names if name.startswith(f'{review_id}_')]}


def _normalize_command(command: list[str] | str) -> list[str]:
    if isinstance(command, str):
        command = shlex.split(command)
    if not command:
        raise ValueError("command must not be empty.")
    executable = Path(command[0]).name
    if executable in RUN_DENYLIST:
        raise ValueError(f"Command '{executable}' is not allowed in the review workspace.")
    return [str(part) for part in command]


def _run_workspace_command(
    review_id: str,
    command: list[str] | str,
    *,
    cwd: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    dirs = _ensure_review_dirs(review_id)
    workspace = dirs["workspace"]
    workdir = _safe_workspace_path(review_id, cwd, must_exist=True) if cwd else workspace
    if not workdir.is_dir():
        raise ValueError("cwd must be a directory inside the review workspace.")
    args = _normalize_command(command)
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(dirs["review"] / "_pycache")
    env["CODE_REVIEW_OUTPUT_DIR"] = str(dirs["outputs"])

    try:
        proc = subprocess.run(
            args,
            cwd=str(workdir),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
        )
        stdout, stdout_truncated = _truncate(proc.stdout, max_chars=8000)
        stderr, stderr_truncated = _truncate(proc.stderr, max_chars=8000)
        log_path = dirs["logs"] / f"run-{int(time.time())}.json"
        log_payload = {
            "command": args,
            "cwd": str(workdir),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        log_path.write_text(json.dumps(log_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": proc.returncode == 0,
            "command": args,
            "cwd": _relative_to(workdir, workspace),
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "log_path": str(log_path),
        }
    except FileNotFoundError as exc:
        return {"ok": False, "error_type": "FileNotFoundError", "error": str(exc), "command": args}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error_type": "TimeoutExpired",
            "error": f"Command timed out after {timeout_seconds} seconds.",
            "command": args,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }


class CodeReviewWorkspaceInput(BaseModel):
    action: Literal[
        "prepare",
        "list",
        "read",
        "run",
        "notebook_info",
        "notebook_read",
        "notebook_execute",
        "notebook_execute_range",
        "notebook_shutdown",
    ] = Field(..., description="Workspace action to perform.")
    review_id: str = Field(..., description="Review id provided by the code_review task.")
    target_paths: list[str] = Field(default_factory=list, description="Original files/directories to copy for prepare.")
    path: str | None = Field(default=None, description="Workspace-relative path for list/read/notebook actions.")
    command: list[str] | str | None = Field(default=None, description="Command to run in the review workspace.")
    cwd: str | None = Field(default=None, description="Workspace-relative command working directory.")
    section: str | None = Field(default=None, description="Notebook markdown section title substring.")
    query: str | None = Field(default=None, description="Notebook source substring query.")
    cell_start: int | None = Field(default=None, description="First notebook cell index, inclusive.")
    cell_end: int | None = Field(default=None, description="Last notebook cell index, inclusive.")
    include_source: bool = Field(default=True, description="Whether notebook_read should include full selected cell source.")
    kernel_name: str | None = Field(default=None, description="Kernel name for notebook execution. Defaults to notebook metadata.")
    timeout_seconds: int = Field(default=120, ge=1, le=7200, description="Timeout for run/notebook execution.")
    max_chars: int = Field(default=DEFAULT_MAX_CHARS, ge=1000, le=50000, description="Maximum returned text characters.")
    restart_kernel: bool = Field(default=True, description="Whether notebook execution should restart the review kernel first.")


class CodeReviewWorkspace(BaseTool):
    name: str = "code_review_workspace"
    description: str = (
        "Operate inside an isolated code review workspace. Use prepare to copy target files into "
        "artifacts/code_review/<review_id>/workspace, then read/list/run or inspect/execute notebook copies. "
        "This tool must not modify original project files or active BioInCoder Jupyter sessions."
    )
    args_schema: type[BaseModel] = CodeReviewWorkspaceInput

    def _run(
        self,
        action: str,
        review_id: str,
        target_paths: list[str] | None = None,
        path: str | None = None,
        command: list[str] | str | None = None,
        cwd: str | None = None,
        section: str | None = None,
        query: str | None = None,
        cell_start: int | None = None,
        cell_end: int | None = None,
        include_source: bool = True,
        kernel_name: str | None = None,
        timeout_seconds: int = 120,
        max_chars: int = DEFAULT_MAX_CHARS,
        restart_kernel: bool = True,
    ) -> dict[str, Any]:
        try:
            dirs = _ensure_review_dirs(review_id)
            workspace = dirs["workspace"]

            if action == "prepare":
                copied = []
                missing = []
                for raw in target_paths or []:
                    source = Path(raw).expanduser()
                    if not source.is_absolute():
                        source = Path.cwd() / source
                    result = _copy_target_to_workspace(source, workspace)
                    copied.append(result)
                    if result.get("status") == "missing":
                        missing.append(raw)
                return {
                    "ok": not missing,
                    "review_id": review_id,
                    "review_dir": str(dirs["review"]),
                    "workspace": str(workspace),
                    "logs": str(dirs["logs"]),
                    "outputs": str(dirs["outputs"]),
                    "copied": copied,
                    "missing_targets": missing,
                }

            if action == "list":
                target = _safe_workspace_path(review_id, path, must_exist=True)
                files, truncated = _list_files(target)
                return {
                    "ok": True,
                    "review_id": review_id,
                    "path": _relative_to(target, workspace),
                    "truncated": truncated,
                    "files": files,
                }

            if action == "read":
                target = _safe_workspace_path(review_id, path, must_exist=True)
                if target.is_dir():
                    files, truncated = _list_files(target)
                    return {"ok": True, "kind": "directory", "path": _relative_to(target, workspace), "files": files, "truncated": truncated}
                return _read_text(target, max_chars=max_chars)

            if action == "run":
                if command is None:
                    raise ValueError("command is required for action='run'.")
                return _run_workspace_command(review_id, command, cwd=cwd, timeout_seconds=timeout_seconds)

            if action == "notebook_info":
                target = _safe_workspace_path(review_id, path, must_exist=True)
                return _notebook_info(target)

            if action == "notebook_read":
                target = _safe_workspace_path(review_id, path, must_exist=True)
                return _notebook_read(
                    target,
                    section=section,
                    query=query,
                    cell_start=cell_start,
                    cell_end=cell_end,
                    include_source=include_source,
                    max_chars=max_chars,
                )

            if action in {"notebook_execute", "notebook_execute_range"}:
                target = _safe_workspace_path(review_id, path, must_exist=True)
                if target.suffix != ".ipynb":
                    raise ValueError("notebook execution actions require an .ipynb path.")
                if action == "notebook_execute":
                    cell_start = None
                    cell_end = None
                return _notebook_execute(
                    review_id,
                    target,
                    kernel_name=kernel_name,
                    cell_start=cell_start,
                    cell_end=cell_end,
                    timeout_seconds=timeout_seconds,
                    restart_kernel=restart_kernel,
                )

            if action == "notebook_shutdown":
                return _notebook_shutdown(review_id, path=path)

            raise ValueError(f"Unsupported action: {action}")
        except Exception as exc:
            return tool_error_response(exc)


class CodeReviewInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    target_paths: list[str] = Field(
        ...,
        description=(
            "Files or directories to review. Include all generated or modified code deliverables. "
            "For section/function-specific reviews, provide the containing file path here and specify "
            "the exact section/function/cell range in task_brief."
        ),
    )
    task_brief: str = Field(
        ...,
        min_length=80,
        description=(
            "Detailed, self-contained review brief for CodeReviewer. Include the user goal, what changed "
            "or was generated, expected inputs/outputs, runtime constraints, expensive stages/checkpoints, "
            "exact partial-review boundaries if any, review priorities, blocking criteria, and explicit out-of-scope items."
        ),
    )
    mode: Literal["fast", "resume", "full"] = Field(
        default="fast",
        description=(
            "Review intensity. fast = static/syntax/structure checks; resume = fast plus isolated resume/smoke "
            "checks where available; full = attempt full clean execution when feasible."
        ),
    )
    review_scope: Literal["changed_files", "selected_paths", "deliverable", "project"] = Field(
        default="selected_paths",
        description=(
            "Breadth of review. changed_files = files modified in the current work; selected_paths = supplied "
            "target_paths and specific parts described in task_brief; deliverable = target_paths plus related "
            "README/environment/output/checkpoint artifacts; project = broader repository-level review."
        ),
    )
    runtime: ToolRuntime


class CodeReview(BaseTool):
    name: str = "code_review"
    description: str = (
        "Call CodeReviewer to independently review generated or modified code, notebooks, scripts, and workflow files. "
        "Use before finalizing non-trivial runnable code deliverables, especially notebooks and bioinformatics analyses. "
        "CodeReviewer receives only the task_brief and target_paths, so the brief must be detailed and self-contained. "
        "Reviews are read-only for original files and use isolated review workspaces."
    )
    args_schema: type[BaseModel] = CodeReviewInput

    def _run(
        self,
        target_paths: list[str],
        task_brief: str,
        runtime: ToolRuntime,
        mode: str = "fast",
        review_scope: str = "selected_paths",
    ):
        review_id: str | None = None
        try:
            from AgentConfigSetup import multi_agent_runtime

            review_id = _now_review_id()
            dirs = _ensure_review_dirs(review_id)

            review_instruction = HumanMessage(
                content=(
                    "CodeReviewer delegated task.\n\n"
                    f"# Review id\n{review_id}\n\n"
                    f"# Review mode\n{mode}\n\n"
                    f"# Review scope\n{review_scope}\n\n"
                    "# Safety boundary\n"
                    "Review original files as read-only. Use code_review_workspace(action='prepare') first "
                    "to copy target paths into an isolated workspace. Perform command execution and notebook "
                    "execution only inside that workspace. Do not modify original files, formal outputs, caches, "
                    "or active Jupyter sessions.\n\n"
                    "# Review workspace paths\n"
                    f"- review_dir: {dirs['review']}\n"
                    f"- workspace: {dirs['workspace']}\n"
                    f"- logs: {dirs['logs']}\n"
                    f"- outputs: {dirs['outputs']}\n\n"
                    "# Target paths\n"
                    + "\n".join(f"- {path}" for path in target_paths)
                    + "\n\n"
                    f"# Task brief\n{task_brief}\n\n"
                    "# Message instruction\n"
                    "Use the task brief as the binding scope. Review both mechanical correctness and alignment "
                    "with the user's stated intent. Use code_review_workspace to prepare, inspect, run safe checks, "
                    "and inspect or execute notebook copies as needed. Return blocking issues first, then non-blocking "
                    "issues, validation evidence, residual risks, and a final verdict."
                )
            )

            request_id = runtime.tool_call_id
            review_config = multi_agent_runtime.make_child_config(
                parent_config=getattr(runtime, "config", None),
                agent_name="CodeReviewer",
                request_id=request_id,
            )
            review_state, message_ref = multi_agent_runtime.invoke_agent(
                agent_name="CodeReviewer",
                graph_input={"messages": [review_instruction]},
                request_id=request_id,
                config=review_config,
            )

            messages = multi_agent_runtime.extract_messages(review_state)
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
                tool_call_id=runtime.tool_call_id,
                hint="Check that CodeReviewer is registered and that task_brief is detailed enough for review.",
            )
        finally:
            if review_id is not None:
                try:
                    _notebook_shutdown(review_id)
                except Exception:
                    pass
