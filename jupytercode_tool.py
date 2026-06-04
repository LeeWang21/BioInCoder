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

    def insert_cell(self, index: int | None, cell_type: str, source: str) -> dict[str, Any]:
        index = self._normalize_insert_index(index)

        if cell_type == "markdown":
            cell = new_markdown_cell(source)
        elif cell_type == "code":
            cell = new_code_cell(source)
        else:
            raise ValueError("cell_type must be 'markdown' or 'code'")

        self.nb.cells.insert(index, cell)
        self.save()
        return {
            "ok": True,
            "cell_index": index,
            "cell_type": cell_type,
            "num_cells": len(self.nb.cells),
        }

    def delete_cell(self, index: int) -> dict[str, Any]:
        self._require_index(index)
        deleted_type = self.nb.cells[index].cell_type
        del self.nb.cells[index]
        self.save()
        return {
            "ok": True,
            "deleted_index": index,
            "deleted_type": deleted_type,
            "num_cells": len(self.nb.cells),
        }
    
    def read_cell(self, index: int) -> dict[str, Any]:
        self._require_index(index)
        cell = self.nb.cells[index]
        return {
            "ok": True,
            "cell_index": index,
            "cell_type": cell.cell_type,
            "source": cell.source,
            "output_preview": self._cell_output_preview(cell, 4000),
            "execution_count": cell.get("execution_count"),
        }

    def overwrite_cell_source(self, index: int, source: str) -> dict[str, Any]:
        self._require_index(index)
        self.nb.cells[index].source = source
        if self.nb.cells[index].cell_type == "code":
            self.nb.cells[index]["outputs"] = []
            self.nb.cells[index]["execution_count"] = None
        self.save()
        return {"ok": True, "cell_index": index}

    def execute_cell(self, index: int) -> dict[str, Any]:
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

        result = self._execute_source(source)

        # Clear the running signal
        try:
            running_path.unlink(missing_ok=True)
        except Exception:
            pass

        cell["outputs"] = result["outputs"]
        cell["execution_count"] = result["execution_count"]
        self.save()

        out = {
            "ok": result["ok"],
            "cell_index": index,
            "execution_count": result["execution_count"],
            "output_preview": result["preview"],
            "error": result.get("error"),
        }

        return out

    def insert_execute_code_cell(self, index: int | None, source: str) -> dict[str, Any]:
        inserted = self.insert_cell(index=index, cell_type="code", source=source)
        idx = inserted["cell_index"]
        executed = self.execute_cell(idx)
        out = {
            "ok": executed["ok"],
            "cell_index": idx,
            "execution_count": executed["execution_count"],
            "output_preview": executed["output_preview"],
            "error": executed.get("error"),
        }

        return out

    def _execute_source(self, source: str) -> dict[str, Any]:
        msg_id = self.kc.execute(source, allow_stdin=False, stop_on_error=True)

        outputs = []
        execution_count = None
        error_text = None

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=10)
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
                return notebook
            else:
                notebook.shutdown()
                del self.nb_collections[name]
                return "The name and notebook_path provided were not match. The notebook is shutdown."

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
    List all currently registered notebook sessions.

    Use this tool when you need to know:
    - which notebook sessions already exist
    - the notebook path for each session
    - which kernel is attached to each session

    This tool is useful before choosing a notebook session name for later operations.

    Do NOT use this tool to inspect notebook cell contents.
    To inspect notebook structure or cell outputs, use `jupytercode_read_notebook` instead.

    Returns:
        A string containing:
            - notebook_name: Session name
            - notebook_path: Path to the notebook file
            - notebook_kernel: Kernel name attached to the session
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
    Open or create a named Jupyter notebook session and make it available for later notebook operations.

    Use this tool first before reading cells, inserting cells, executing code, deleting cells,
    or restarting the kernel for a notebook session.
    
    Behavior:
    - If the notebook file already exists, it will be loaded.
    - If the notebook file does not exist, a new notebook file will be created.
    - A live Jupyter kernel will be started for this notebook session.
    - Later notebook tools should use the same `name` to operate on this session.

    Recommended use cases:
    - Start a new analysis notebook session.
    - Re-open an existing notebook and continue working in it.
    - Create a notebook-backed execution environment for iterative coding.

    Do NOT use this tool if you only want to inspect a notebook session that is already open;
    use the same `name` with the other notebook tools instead.

    Args:
        name: Unique name used to identify this notebook session in later tool calls.
        notebook_path: Absolute or relative path to the target `.ipynb` notebook file.
        kernel_name: Jupyter kernel name for this notebook session. You should check the jupyter kernel informations and package informations in kernel to choose proper kernel.

    Returns:
        A dictionary containing:
        - ok: Whether the operation succeeded.
        - notebook_name: Name of the notebook session.
        - notebook_path: Resolved notebook file path.
        - notebook_kernel: Kernel name associated with this session.
        - num_cells: Current number of cells in the notebook.
    """
    notebook = JUPYTER_REGISTRY.use_notebook(name, notebook_path, kernel_name)
    out = {
        "ok": True,
        "notebook_name": name,
        "notebook_path": str(notebook.path),
        "notebook_kernel": kernel_name,
        "user_id": notebook.user_id,
        "session_id": notebook.session_id,
        "num_cells": len(notebook.nb.cells),
    }
    return out

@tool
def jupytercode_read_notebook(name: str) -> dict[str, Any]:
    """
    Read a named notebook session and return a structured overview of all cells.

    Use this tool before editing or executing cells when you need to understand:
    - notebook structure
    - existing code cells
    - markdown notes
    - recent outputs

    This tool is especially useful for deciding where to insert new cells,
    whether an existing cell should be modified, and what has already been executed.

    Prefer this tool over reading cells one-by-one when you need a notebook-level overview.

    Args:
        name: Name of the notebook session to inspect.

    Returns:
        A dictionary containing:
        - ok: Whether the operation succeeded.
        - notebook_path: Path of the notebook file.
        - num_cells: Total number of cells.
        - cells: List of cell summaries, each including:
            - index
            - cell_type
            - source_preview
            - output_preview
    """
    return JUPYTER_REGISTRY.current_notebook(name).read_notebook()

@tool
def jupytercode_read_cell(name: str, index: int) -> dict[str, Any]:
    """
    Read one specific cell from a named notebook session.

    Use this tool when you need the full source and current output of a single cell
    before deciding whether to modify it, execute it, or delete it.

    This is the preferred tool when:
    - you already know the target cell index
    - you need full source code instead of only a preview
    - you want to inspect the current output of one cell in detail

    Args:
        name: Name of the notebook session.
        index: Zero-based index of the target cell.

    Returns:
        A dictionary containing:
        - ok: Whether the operation succeeded.
        - cell_index: Requested cell index.
        - cell_type: `code` or `markdown`.
        - source: Full source content of the cell.
        - output_preview: Summarized preview of current outputs.
        - execution_count: Execution count if the cell is a code cell.
    """
    return JUPYTER_REGISTRY.current_notebook(name).read_cell(index)

@tool
def jupytercode_insert_cell(name: str, index: int | None, cell_type: str, source: str) -> dict[str, Any]:
    """
    Insert a new cell into a named notebook session without executing it.

    Use this tool when you want to add notebook content first and execute later,
    or when you want to add markdown explanations, notes, or code placeholders.

    Important:
    - This tool does NOT execute the new cell.
    - If `index` is None, negative, or out of range, the cell will be appended to the end.
    - the `cell_type` argument currently supports
      both `markdown` and `code`. Use `markdown` for notes and explanations, and `code`
      when you want to insert code without executing it yet.

    Good use cases:
    - Add markdown notes that explain an analysis step.
    - Insert a code cell draft before reviewing or editing it.
    - Prepare a notebook structure before execution.

    Args:
        name: Name of the notebook session.
        index: Position where the new cell should be inserted. Use None to append.
        cell_type: Type of the cell. Must be `markdown` or `code`.
        source: Source content of the new cell.

    Returns:
        A dictionary containing:
        - ok: Whether the operation succeeded.
        - cell_index: Index of the inserted cell.
        - cell_type: Inserted cell type.
        - num_cells: Updated number of cells in the notebook.
    """
    session = JUPYTER_REGISTRY.current_notebook(name)
    out = session.insert_cell(index=index, cell_type=cell_type, source=source)
    return out

@tool
def jupytercode_execute_cell(name: str, index: int) -> dict[str, Any]:
    """
    Execute one existing code cell in a named notebook session using that session's live Jupyter kernel.

    Use this tool when:
    - the target code already exists in the notebook
    - you want to re-run a previously inserted or edited code cell
    - you want the execution outputs to be recorded back into the notebook

    Important:
    - This tool only executes an existing cell.
    - It does NOT insert a new cell.
    - The target cell must be a code cell, not a markdown cell.
    - Execution happens in the live kernel attached to this notebook session, so previously created
      variables and objects in that session may still be available.

    Prefer this tool over `jupytercode_insert_execute_code_cell` when the code is already in the notebook.
    Prefer `jupytercode_insert_execute_code_cell` when you want to add a fresh code cell and run it immediately.

    Args:
        name: Name of the notebook session.
        index: Zero-based index of the code cell to execute.

    Returns:
        A dictionary containing:
        - ok: Whether execution succeeded.
        - cell_index: Executed cell index.
        - execution_count: Kernel execution count.
        - output_preview: Summarized preview of outputs.
        - error: Traceback summary if execution failed.
        - paused_by_user: Whether execution was interrupted by the user.
    """
    session = JUPYTER_REGISTRY.current_notebook(name)
    out = session.execute_cell(index=index)
    return out

@tool
def jupytercode_insert_execute_code_cell(name: str, index: int | None, source: str) -> dict[str, Any]:
    """
    Insert a new code cell into a named notebook session and execute it immediately in that session's live kernel.

    This is the main tool for iterative notebook coding.

    Use this tool when you want to:
    - add fresh code to the notebook
    - run it right away
    - record both the code and its outputs in the notebook

    Important:
    - The code is executed in the live kernel attached to this notebook session.
    - Variables and objects created earlier in the same session may still exist and can be reused.
    - The language of the code must match the session's kernel. For example:
      - use Python code for a Python kernel
      - use R code for an R kernel
    - If you want to execute an existing cell instead of inserting a new one, use `jupytercode_execute_cell` if available.

    Prefer this tool over plain cell insertion when you want immediate execution and recorded outputs.

    Args:
        name: Name of the notebook session.
        index: Position to insert the new code cell. Use None to append to the end.
        source: Source code to insert and execute. It should match the notebook session's kernel language.

    Returns:
        A dictionary containing:
        - ok: Whether execution succeeded.
        - cell_index: Index of the inserted cell.
        - execution_count: Kernel execution count.
        - output_preview: Summarized preview of outputs.
        - error: Traceback summary if execution failed.
    """
    session = JUPYTER_REGISTRY.current_notebook(name)
    inserted = session.insert_cell(index=index, cell_type="code", source=source)
    executed = session.execute_cell(inserted["cell_index"])
    out = {
        "ok": executed["ok"],
        "cell_index": inserted["cell_index"],
        "execution_count": executed["execution_count"],
        "output_preview": executed["output_preview"],
        "error": executed.get("error"),
    }
    return out

@tool
def jupytercode_delete_cell(name: str, index: int) -> dict[str, Any]:
    """
    Delete one cell from a named notebook session.

    Use this tool only when you are confident that the target cell should be removed.
    Typical reasons include:
    - the cell is no longer useful
    - the cell contains failed or outdated code
    - the notebook needs cleanup before continuing

    Best practice:
    - Prefer `jupytercode_read_notebook` or `jupytercode_read_cell` first if you are not fully sure.
    - Avoid deleting cells that may still be needed for reproducibility or context.

    Args:
        name: Name of the notebook session.
        index: Zero-based index of the cell to delete.

    Returns:
        A dictionary containing:
        - ok: Whether the operation succeeded.
        - deleted_index: Index of the deleted cell.
        - deleted_type: Type of the deleted cell.
        - num_cells: Updated total number of cells.
    """
    session = JUPYTER_REGISTRY.current_notebook(name)
    out = session.delete_cell(index=index)
    return out

@tool
def jupytercode_overwrite_cell_source(name: str, index: int, source: str) -> dict[str, Any]:
    """
    Replace the source content of one existing cell in a named notebook session without executing it.

    Use this tool when:
    - an existing cell should be rewritten
    - code or markdown needs to be corrected
    - a failed cell should be edited before re-execution

    Important:
    - This tool only changes the cell source.
    - It does NOT execute the cell.
    - For code cells, previous outputs and execution count will be cleared after overwrite.

    Recommended workflow:
    1. Use `jupytercode_read_cell` first if you need to inspect the current source.
    2. Use this tool to replace the source.
    3. Use `execute_cell` if you want to run the updated code.

    Args:
        name: Name of the notebook session.
        index: Zero-based index of the target cell.
        source: New full source content for the cell.

    Returns:
        A dictionary containing:
        - ok: Whether the operation succeeded.
        - cell_index: Index of the modified cell.
    """
    session = JUPYTER_REGISTRY.current_notebook(name)
    out = session.overwrite_cell_source(index=index, source=source)
    return out

@tool
def jupytercode_restart_kernel(name: str) -> dict[str, Any]:
    """
    Restart the live Jupyter kernel for a named notebook session.

    Use this tool when:
    - the kernel state is corrupted
    - variables should be cleared
    - memory should be released
    - the execution environment must be reset before continuing

    Warning:
    - Restarting the kernel clears all in-memory variables, objects, and session state
      created in the current notebook kernel.
    - Notebook cells and saved outputs remain in the notebook file, but live runtime state is lost.

    Do NOT use this tool unless a reset is truly needed.

    Args:
        name: Name of the notebook session.

    Returns:
        A dictionary containing:
        - ok: Whether the restart succeeded.
        - notebook_path: Path of the notebook file associated with the restarted session.
    """
    session = JUPYTER_REGISTRY.current_notebook(name)
    session.restart_kernel()
    return {"ok": True, "notebook_path": str(session.path)}


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
            jupytercode_execute_cell,
            jupytercode_insert_execute_code_cell,
            jupytercode_delete_cell,
            jupytercode_overwrite_cell_source,
            jupytercode_restart_kernel
        ]
