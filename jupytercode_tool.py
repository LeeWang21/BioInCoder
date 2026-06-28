import queue
import json
import re
import time
from pathlib import Path
from typing import Any

import nbformat as nbf
from nbformat.v4 import (
    new_code_cell,
    new_markdown_cell,
    new_notebook,
    new_output,
)
from jupyter_client import KernelManager

from langchain_core.tools import BaseTool, BaseToolkit, tool


SOURCE_PREVIEW_CHARS = 1600


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------

def strip_code_fences(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"^```[^\n]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def ok_response(**kwargs) -> dict[str, Any]:
    return {"ok": True, **kwargs}


def error_response(error: Exception | str, error_type: str | None = None, hint: str | None = None) -> dict[str, Any]:
    if isinstance(error, Exception):
        error_type = error_type or type(error).__name__
        error_text = str(error)
    else:
        error_type = error_type or "Error"
        error_text = error

    out: dict[str, Any] = {
        "ok": False,
        "error_type": error_type,
        "error": error_text,
    }
    if hint:
        out["hint"] = hint
    return out


# -----------------------------------------------------------------------------
# NotebookSession + kernel state
# -----------------------------------------------------------------------------

class NotebookSession:
    def __init__(
        self,
        name: str,
        notebook_path: str,
        kernel_name: str,
        user_id: str | None = None,
        session_id: str | None = None,
    ):
        self.name = name
        self.user_id = user_id
        self.session_id = session_id

        self.path = Path(notebook_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if self.path.exists():
            self.nb = nbf.read(self.path, as_version=4)
        else:
            self.nb = new_notebook()

        self.kernel_name = kernel_name
        self.km = KernelManager(kernel_name = self.kernel_name)
        self.km.start_kernel(cwd=str(self.path.parent))

        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=60)
        self.setup_executed = False
        self.created_scripts: list[str] = []
        self.running_cell_index: int | None = None
        self.execution_started_at: float | None = None
        self.last_execution_ended_at: float | None = None
        self.last_error: str | None = None
        self.last_execution_count: int | None = None

        self.save()

    def shutdown(self) -> None:
        try:
            if self.kc is not None:
                self.kc.stop_channels()
        except Exception:
            pass

        try:
            if self.km is not None:
                self.km.shutdown_kernel(now=False)
        except Exception:
            try:
                self.km.shutdown_kernel(now=True)
            except Exception:
                pass

    def restart_kernel(self) -> None:
        self.shutdown()
        self.km = KernelManager(kernel_name = self.kernel_name)
        self.km.start_kernel(cwd=str(self.path.parent))
        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=60)
        self.setup_executed = False
        self.running_cell_index = None
        self.execution_started_at = None
        self.last_error = None

    def interrupt_kernel(self) -> None:
        if self.km is None:
            raise RuntimeError("Kernel manager is not available.")
        self.km.interrupt_kernel()

    def status(self) -> dict[str, Any]:
        is_alive = bool(self.km and self.km.is_alive())
        return ok_response(
            notebook_name=self.name,
            notebook_path=str(self.path),
            kernel_name=self.kernel_name,
            kernel_alive=is_alive,
            user_id=self.user_id,
            session_id=self.session_id,
            num_cells=len(self.nb.cells),
            running_cell_index=self.running_cell_index,
            execution_started_at=self.execution_started_at,
            last_execution_ended_at=self.last_execution_ended_at,
            last_execution_count=self.last_execution_count,
            last_error=self.last_error,
        )

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            nbf.write(self.nb, f)

    def read_notebook(self) -> dict[str, Any]:
        # Reload from disk to pick up user edits
        if self.path.exists():
            self.nb = nbf.read(self.path, as_version=4)
        cells = []
        for i, cell in enumerate(self.nb.cells):
            cells.append({
                "index": i,
                "cell_type": cell.cell_type,
                "source_preview": self._trim(cell.source, 600),
                "output_preview": self._cell_output_preview(cell, 1200),
            })
        return {
            "ok": True,
            "notebook_name": self.name,
            "notebook_path": str(self.path),
            "kernel_name": self.kernel_name,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "num_cells": len(self.nb.cells),
            "cells": cells,
        }

    def _normalize_insert_index(self, index: int | None) -> int:
        if index is None or index < 0 or index > len(self.nb.cells):
            return len(self.nb.cells)
        return index

    def _require_index(self, index: int) -> None:
        if index < 0 or index >= len(self.nb.cells):
            raise IndexError(f"Cell index {index} out of range (0..{len(self.nb.cells)-1})")

    def _bioincoder_metadata(self, tool_name: str, status: str = "created") -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "notebook_name": self.name,
            "tool": tool_name,
            "status": status,
            "updated_at": now_str(),
        }

    def _stamp_cell(self, cell: Any, tool_name: str, status: str = "created") -> None:
        metadata = dict(cell.get("metadata", {}))
        metadata["bioincoder"] = self._bioincoder_metadata(tool_name=tool_name, status=status)
        cell["metadata"] = metadata

    def insert_cell(self, index: int | None, cell_type: str, source: str, tool_name: str = "jupytercode_insert_cell") -> dict[str, Any]:
        index = self._normalize_insert_index(index)
        source = strip_code_fences(source) if cell_type == "code" else source

        if cell_type == "markdown":
            cell = new_markdown_cell(source)
        elif cell_type == "code":
            cell = new_code_cell(source)
        else:
            raise ValueError("cell_type must be 'markdown' or 'code'")

        self._stamp_cell(cell, tool_name=tool_name)
        self.nb.cells.insert(index, cell)
        self.save()
        return ok_response(
            cell_index=index,
            cell_type=cell_type,
            num_cells=len(self.nb.cells),
        )

    def delete_cell(self, index: int) -> dict[str, Any]:
        self._require_index(index)
        deleted_type = self.nb.cells[index].cell_type
        del self.nb.cells[index]
        self.save()
        return ok_response(
            deleted_index=index,
            deleted_type=deleted_type,
            num_cells=len(self.nb.cells),
        )
    
    def read_cell(self, index: int) -> dict[str, Any]:
        self._require_index(index)
        cell = self.nb.cells[index]
        return ok_response(
            cell_index=index,
            cell_type=cell.cell_type,
            source=cell.source,
            output_preview=self._cell_output_preview(cell, 4000),
            execution_count=cell.get("execution_count"),
        )

    def overwrite_cell_source(self, index: int, source: str) -> dict[str, Any]:
        self._require_index(index)
        if self.nb.cells[index].cell_type == "code":
            source = strip_code_fences(source)
        self.nb.cells[index].source = source
        if self.nb.cells[index].cell_type == "code":
            self.nb.cells[index]["outputs"] = []
            self.nb.cells[index]["execution_count"] = None
        self._stamp_cell(self.nb.cells[index], tool_name="jupytercode_overwrite_cell_source")
        self.save()
        return ok_response(cell_index=index)

    def execute_cell(self, index: int, timeout_seconds: int | None = 1800) -> dict[str, Any]:
        self._require_index(index)
        cell = self.nb.cells[index]
        if cell.cell_type != "code":
            raise ValueError(f"Cell {index} is not a code cell")

        source = cell.source
        if isinstance(source, list):
            source = "\n".join(source)

        # Signal to the GUI that this cell is executing
        running_path = self.path.parent / ".running_cell.log"
        try:
            running_path.write_text(json.dumps({
                "cell_index": index,
                "started_at": time.time(),
            }), encoding="utf-8")
        except Exception:
            pass

        self.running_cell_index = index
        self.execution_started_at = time.time()
        self.last_error = None

        try:
            result = self._execute_source(source, timeout_seconds=timeout_seconds)
        except Exception as exc:
            result = self._execution_exception_result(exc)
        finally:
            # Clear the running signal
            try:
                running_path.unlink(missing_ok=True)
            except Exception:
                pass

        self.running_cell_index = None
        self.last_execution_ended_at = time.time()
        self.last_error = result.get("error")
        self.last_execution_count = result["execution_count"]

        cell["outputs"] = result["outputs"]
        cell["execution_count"] = result["execution_count"]
        self._stamp_cell(
            cell,
            tool_name="jupytercode_execute_cell",
            status="ok" if result["ok"] else "error",
        )
        self.save()

        out = ok_response(
            cell_index=index,
            source_preview=self._trim(source, SOURCE_PREVIEW_CHARS),
            execution_count=result["execution_count"],
            output_preview=result["preview"],
            error=result.get("error"),
            timed_out=result.get("timed_out", False),
        )
        out["ok"] = result["ok"]

        return out

    def _execution_exception_result(self, exc: Exception) -> dict[str, Any]:
        error_text = f"{type(exc).__name__}: {exc}"
        outputs = [
            new_output(
                output_type="error",
                ename=type(exc).__name__,
                evalue=str(exc),
                traceback=[error_text],
            )
        ]
        return {
            "ok": False,
            "outputs": outputs,
            "execution_count": None,
            "preview": error_text,
            "error": error_text,
            "timed_out": False,
        }

    def insert_execute_code_cell(self, index: int | None, source: str, timeout_seconds: int | None = 1800) -> dict[str, Any]:
        inserted = self.insert_cell(
            index=index,
            cell_type="code",
            source=source,
            tool_name="jupytercode_insert_execute_code_cell",
        )
        idx = inserted["cell_index"]
        executed = self.execute_cell(idx, timeout_seconds=timeout_seconds)
        out = ok_response(
            cell_index=idx,
            source_preview=self._trim(source, SOURCE_PREVIEW_CHARS),
            execution_count=executed["execution_count"],
            output_preview=executed["output_preview"],
            error=executed.get("error"),
            timed_out=executed.get("timed_out", False),
        )
        out["ok"] = executed["ok"]

        return out

    def _execute_source(self, source: str, timeout_seconds: int | None = 1800) -> dict[str, Any]:
        msg_id = self.kc.execute(source, allow_stdin=False, stop_on_error=True)

        outputs = []
        execution_count = None
        error_text = None
        timed_out = False
        started = time.monotonic()
        timeout_enabled = timeout_seconds is not None and timeout_seconds > 0

        while True:
            if timeout_enabled and time.monotonic() - started > timeout_seconds:
                timed_out = True
                error_text = f"Cell execution timed out after {timeout_seconds} seconds."
                try:
                    self.interrupt_kernel()
                except Exception as exc:
                    error_text += f" Kernel interrupt failed: {exc}"
                outputs.append(new_output(
                    output_type="error",
                    ename="TimeoutError",
                    evalue=error_text,
                    traceback=[error_text],
                ))
                break

            try:
                msg = self.kc.get_iopub_msg(timeout=1)
            except queue.Empty:
                continue
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue

            msg_type = msg["msg_type"]
            content = msg["content"]

            if msg_type == "status":
                if content.get("execution_state") == "idle":
                    break

            elif msg_type == "execute_input":
                execution_count = content.get("execution_count", execution_count)

            elif msg_type == "stream":
                outputs.append(new_output(
                    output_type="stream",
                    name=content["name"],
                    text=content["text"],
                ))

            elif msg_type == "display_data":
                outputs.append(new_output(
                    output_type="display_data",
                    data=content["data"],
                    metadata=content.get("metadata", {}),
                ))

            elif msg_type == "execute_result":
                execution_count = content.get("execution_count", execution_count)
                outputs.append(new_output(
                    output_type="execute_result",
                    data=content["data"],
                    metadata=content.get("metadata", {}),
                    execution_count=execution_count,
                ))

            elif msg_type == "error":
                outputs.append(new_output(
                    output_type="error",
                    ename=content["ename"],
                    evalue=content["evalue"],
                    traceback=content["traceback"],
                ))
                error_text = "\n".join(content["traceback"][-8:])

            elif msg_type == "clear_output":
                outputs = []

        preview = self._outputs_preview(outputs, 4000)
        ok = error_text is None


        return {
            "ok": ok,
            "outputs": outputs,
            "execution_count": execution_count,
            "preview": preview,
            "error": error_text,
            "timed_out": timed_out,
        }

    @staticmethod
    def _trim(text: str, limit: int) -> str:
        text = text or ""
        return text if len(text) <= limit else text[:limit] + "...[truncated]"

    def _cell_output_preview(self, cell: Any, limit: int) -> str:
        outputs = cell.get("outputs", []) if cell.cell_type == "code" else []
        return self._outputs_preview(outputs, limit)

    def _outputs_preview(self, outputs: list[Any], limit: int) -> str:
        parts = []

        for out in outputs:
            ot = out.get("output_type")

            if ot == "stream":
                parts.append(out.get("text", ""))

            elif ot in ("display_data", "execute_result"):
                data = out.get("data", {})
                if "text/plain" in data:
                    parts.append(str(data["text/plain"]))
                elif "image/png" in data:
                    parts.append("[image/png output]")
                elif "text/html" in data:
                    parts.append("[text/html output]")
                else:
                    parts.append("[rich output]")

            elif ot == "error":
                parts.append("\n".join(out.get("traceback", [])))

        joined = "\n".join(parts).strip()
        return self._trim(joined, limit)


# -----------------------------------------------------------------------------
# NotebookRegistry
# -----------------------------------------------------------------------------
class NotebookRegistry:
    def __init__(self, user_id: str | None = None, session_id: str | None = None):
        self.user_id = user_id
        self.session_id = session_id
        self.nb_collections: dict[str, NotebookSession] = {}
        self.current: NotebookSession | None = None

    def configure(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        overwrite: bool = True,
    ) -> None:
        if overwrite or self.user_id is None:
            self.user_id = user_id
        if overwrite or self.session_id is None:
            self.session_id = session_id

    def use_notebook(self, name: str, notebook_path: str, kernel_name: str) -> NotebookSession:
        if name in self.nb_collections:
            notebook = self.nb_collections[name]
            if str(notebook.path) == str(Path(notebook_path).resolve()):
                if (
                    self.user_id is not None
                    and notebook.user_id is not None
                    and self.user_id != notebook.user_id
                ):
                    raise PermissionError(
                        f"Notebook session '{name}' belongs to user_id={notebook.user_id}, "
                        f"but current registry user_id={self.user_id}."
                    )
                if (
                    self.session_id is not None
                    and notebook.session_id is not None
                    and self.session_id != notebook.session_id
                ):
                    raise PermissionError(
                        f"Notebook session '{name}' belongs to session_id={notebook.session_id}, "
                        f"but current registry session_id={self.session_id}."
                    )
                return notebook
            else:
                raise ValueError(
                    f"Notebook session name '{name}' is already bound to {notebook.path}, "
                    f"not {Path(notebook_path).resolve()}. Use a different name or shut down the old session first."
                )

        else:
            notebook = NotebookSession(
                name=name,
                notebook_path=notebook_path,
                kernel_name=kernel_name,
                user_id=self.user_id,
                session_id=self.session_id,
            )
            self.nb_collections[name] = notebook
            return notebook
        
    def shutdown_notebook(self, name: str):
        if name not in self.nb_collections:
            raise ValueError(f"No notebook session named '{name}' to shutdown")
        else:
            self.nb_collections[name].shutdown()
            del self.nb_collections[name]
            if self.current and self.current.name == name:
                self.current = None

    def current_notebook(self, name: str) -> NotebookSession:
        if name not in self.nb_collections:
            raise ValueError(f"No notebook session named '{name}'")
        else:
            self.current = self.nb_collections[name]
            return self.current
        
    def shutdown_all(self):
        for name, session in list(self.nb_collections.items()):
            try:
                session.shutdown()
            except Exception as e:
                print(f"Failed to shutdown notebook session '{name}': {e}")
        self.nb_collections.clear()
        self.current = None

    def list_sessions(self) -> list[str]:
        return list(self.nb_collections.keys())

    def get(self, name: str) -> NotebookSession:
        return self.current_notebook(name)

    def register(self, name: str, session: NotebookSession, overwrite: bool = False) -> None:
        if name in self.nb_collections and not overwrite:
            raise ValueError(f"Notebook session '{name}' is already registered.")
        self.nb_collections[name] = session

    def control(self, name: str, action: str) -> dict[str, Any]:
        if action == "status":
            return self.current_notebook(name).status()
        if action == "interrupt":
            session = self.current_notebook(name)
            session.interrupt_kernel()
            return ok_response(action=action, notebook_name=name)
        if action == "restart":
            session = self.current_notebook(name)
            session.restart_kernel()
            return ok_response(action=action, notebook_name=name, notebook_path=str(session.path))
        if action == "shutdown":
            self.shutdown_notebook(name)
            return ok_response(action=action, notebook_name=name)

        raise ValueError("action must be one of: status, interrupt, restart, shutdown")



# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------
JUPYTER_REGISTRY = NotebookRegistry()
# Backward-compatible alias for older imports.
JUPYTEREGISTRY = JUPYTER_REGISTRY

@tool
def jupytercode_kernel_selection() -> str:
    """
    Guide the LLM to select the most appropriate Jupyter kernel for executing code.

    This function does not select or start a kernel directly. It provides concise
    instructions for how an LLM or agent should inspect available kernels and choose
    the best one.
    """

    return """
    Step 1: List available kernels
        Command:
            jupyter kernelspec list

        Purpose:
            Find all installed Jupyter kernels and their kernelspec paths.

    Step 2: Inspect kernel.json
        For each candidate kernel, inspect:
            <kernel_path>/kernel.json

        Important fields:
            - "argv": the actual command used to start the kernel
            - "display_name": the human-readable kernel name
            - "language": the kernel language, such as python or R
            - "env": optional environment variables

        Do not select a kernel only by display_name.
        Always check argv to understand the real interpreter or environment.

    Step 3: Detect the code language

        Python indicators:
            - import pandas, import numpy, import scanpy, import torch
            - from ... import ...
            - def, class, with, async, await
            - Python-style indentation

        R indicators:
            - library(...), require(...)
            - <- or %>%
            - data.frame(...), matrix(...)
            - ggplot(...), Seurat functions such as CreateSeuratObject

        Bash / shell indicators:
            - ls, cd, grep, awk, sed
            - samtools, bcftools, cellranger, vartrix
            - #!/bin/bash or %%bash

    Step 4: Check required packages

        For Python kernels:
            Use the python path from argv, then check:
                <python_path> -c "import sys; print(sys.executable); print(sys.version)"
                <python_path> -m pip list

            If needed, test imports:
                <python_path> -c "import scanpy, pandas, numpy"

        For R kernels:
            Use the R path from argv when available, then check:
                <R_path> --version
                <R_path> -e "installed.packages()[, c('Package', 'Version')]"

            If needed, test packages:
                <R_path> -e "library(Seurat)"
                <R_path> -e "library(ggplot2)"

        For Bash-heavy workflows:
            A Jupyter kernel may not be ideal.
            Prefer a shell executor if the task mainly runs command-line tools.

    Step 5: Selection rules

        1. Match the language first.
            Python code -> Python kernel.
            R code -> R kernel.
            Bash-heavy code -> shell executor if available.

        2. Match required packages.
            Choose the kernel where required packages are already installed.

        3. Prefer project-specific environments.
            For example, prefer scrna_env over generic python3 for scRNA-seq tasks.

        4. Check hardware needs.
            If GPU is required, choose a Python kernel that can access CUDA:
                python -c "import torch; print(torch.cuda.is_available())"

        5. Avoid modifying environments unless explicitly allowed.
            If packages are missing, report them instead of installing automatically.

    """

@tool
def jupytercode_notebooks_info() -> str:
    """
    List registered notebook sessions with path, kernel, user_id, and session_id.

    Use before choosing a notebook session name. This does not inspect cells;
    use jupytercode_read_notebook for notebook contents.
    """
    if not JUPYTER_REGISTRY.nb_collections:
        return "No registered notebook session."

    lines = []
    for name, session in JUPYTER_REGISTRY.nb_collections.items():
        lines.append(
            (
                f"Notebook '{name}': path={session.path}, kernel={session.kernel_name}, "
                f"user_id={session.user_id}, session_id={session.session_id}"
            )
        )
    return "\n".join(lines)

@tool
def jupytercode_use_notebook(name: str, notebook_path: str, kernel_name: str) -> dict[str, Any]:
    """
    Open or create a named notebook session with a live Jupyter kernel.

    Use before reading, editing, or executing cells. Existing session names are
    reused only when path, user_id, and session_id are compatible.
    Returns ok, notebook_name, notebook_path, notebook_kernel, user_id, session_id, num_cells.
    """
    try:
        notebook = JUPYTER_REGISTRY.use_notebook(name, notebook_path, kernel_name)
        return ok_response(
            notebook_name=name,
            notebook_path=str(notebook.path),
            notebook_kernel=kernel_name,
            user_id=notebook.user_id,
            session_id=notebook.session_id,
            num_cells=len(notebook.nb.cells),
        )
    except Exception as exc:
        return error_response(exc, hint="Use a unique notebook name, or shut down the existing session first.")

@tool
def jupytercode_read_notebook(name: str) -> dict[str, Any]:
    """
    Read a notebook-level overview for an opened notebook session.

    Use before editing or executing when cell positions are uncertain.
    Returns notebook metadata and cells with index, cell_type, source_preview, output_preview.
    """
    try:
        return JUPYTER_REGISTRY.current_notebook(name).read_notebook()
    except Exception as exc:
        return error_response(exc, hint="Open the notebook first with jupytercode_use_notebook.")

@tool
def jupytercode_read_cell(name: str, index: int) -> dict[str, Any]:
    """
    Read one cell from an opened notebook session.

    Use when you need full source or output for a known cell index.
    Returns ok, cell_index, cell_type, source, output_preview, execution_count.
    """
    try:
        return JUPYTER_REGISTRY.current_notebook(name).read_cell(index)
    except Exception as exc:
        return error_response(exc, hint="Check the notebook name and cell index with jupytercode_read_notebook.")

@tool
def jupytercode_insert_cell(name: str, index: int | None, cell_type: str, source: str) -> dict[str, Any]:
    """
    Insert a markdown or code cell without executing it.

    Use index=None to append. cell_type must be "markdown" or "code".
    Returns ok, cell_index, cell_type, num_cells.
    """
    try:
        session = JUPYTER_REGISTRY.current_notebook(name)
        return session.insert_cell(index=index, cell_type=cell_type, source=source)
    except Exception as exc:
        return error_response(exc, hint="Open the notebook first and use cell_type='markdown' or 'code'.")

@tool
def jupytercode_execute_cell(name: str, index: int, timeout_seconds: int = 1800) -> dict[str, Any]:
    """
    Execute an existing code cell and save outputs back to the notebook.

    Use for rerunning known code cells. Set timeout_seconds=0 for intentional long jobs.
    Returns ok, cell_index, execution_count, output_preview, error, timed_out.
    """
    try:
        session = JUPYTER_REGISTRY.current_notebook(name)
        return session.execute_cell(index=index, timeout_seconds=timeout_seconds)
    except Exception as exc:
        return error_response(exc, hint="Check the cell index and kernel status with jupytercode_session_control(action='status').")

@tool
def jupytercode_insert_execute_code_cell(name: str, index: int | None, source: str, timeout_seconds: int = 1800) -> dict[str, Any]:
    """
    Insert a code cell and execute it immediately.

    This is the main iterative analysis tool. Use index=None to append.
    Code must match the notebook kernel language. Set timeout_seconds=0 for long jobs.
    Returns ok, cell_index, execution_count, output_preview, error, timed_out.
    """
    try:
        session = JUPYTER_REGISTRY.current_notebook(name)
        return session.insert_execute_code_cell(
            index=index,
            source=source,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return error_response(exc, hint="Open the notebook first. Set timeout_seconds=0 for intentionally long-running code.")

@tool
def jupytercode_delete_cell(name: str, index: int) -> dict[str, Any]:
    """
    Delete one notebook cell by index.

    Use only after confirming the target with read_notebook or read_cell.
    Returns ok, deleted_index, deleted_type, num_cells.
    """
    try:
        session = JUPYTER_REGISTRY.current_notebook(name)
        return session.delete_cell(index=index)
    except Exception as exc:
        return error_response(exc, hint="Read the notebook first to confirm the target cell index.")

@tool
def jupytercode_overwrite_cell_source(name: str, index: int, source: str) -> dict[str, Any]:
    """
    Replace one cell's source without executing it.

    For code cells, previous outputs and execution_count are cleared.
    Use read_cell first when unsure. Returns ok, cell_index.
    """
    try:
        session = JUPYTER_REGISTRY.current_notebook(name)
        return session.overwrite_cell_source(index=index, source=source)
    except Exception as exc:
        return error_response(exc, hint="Read the target cell before overwriting it.")

@tool
def jupytercode_session_control(name: str, action: str) -> dict[str, Any]:
    """
    Inspect or control a notebook session.

    action must be "status", "interrupt", "restart", or "shutdown".
    Status returns kernel liveness, running cell, last execution, and notebook metadata.
    """
    try:
        return JUPYTER_REGISTRY.control(name=name, action=action)
    except Exception as exc:
        return error_response(
            exc,
            hint="Use action='status', 'interrupt', 'restart', or 'shutdown'. Open the notebook first if needed.",
        )


@tool
def jupytercode_restart_kernel(name: str) -> dict[str, Any]:
    """
    Backward-compatible restart wrapper.

    Prefer jupytercode_session_control(name, action="restart").
    """
    try:
        return JUPYTER_REGISTRY.control(name=name, action="restart")
    except Exception as exc:
        return error_response(exc, hint="Prefer jupytercode_session_control(action='restart').")


# -----------------------------------------------------------------------------
# ToolKit
# -----------------------------------------------------------------------------
class JupyterCodeToolkit(BaseToolkit):
    
    def get_tools(self) -> list[BaseTool]:
        return [
            jupytercode_kernel_selection,
            jupytercode_notebooks_info,
            jupytercode_use_notebook,
            jupytercode_read_notebook,
            jupytercode_read_cell,
            jupytercode_insert_cell,
            jupytercode_insert_execute_code_cell,
            jupytercode_delete_cell,
            jupytercode_overwrite_cell_source,
            jupytercode_session_control,
        ]
