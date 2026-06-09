---
name: bioincoder-jupytercode
description: Use BioInCoder's Jupytercode tools for notebook-backed interactive coding, iterative data analysis, kernel/session management, and reproducible analysis notebooks. Use when writing, editing, running, debugging, or organizing analysis code in a Jupyter notebook through tools such as jupytercode_use_notebook, jupytercode_read_notebook, jupytercode_insert_execute_code_cell, and jupytercode_session_control.
---

# Jupytercode Interactive Coding

Use this skill when BioInCoder should perform notebook-backed interactive coding or data analysis through the Jupytercode tool family.

This skill is best suited for **interactive analysis**: iterative coding, inspecting intermediate objects, debugging data issues, refining parameters, and progressively building an analysis workflow.

The final notebook should be a **well-organized analysis notebook**, not a raw code recorder:
- keep the final notebook complete, ordered, and readable from top to bottom;
- organize the workflow into clear sections;
- preserve only meaningful setup, analysis, diagnostics, results, and conclusions;
- remove disposable failed attempts, temporary debug cells, and misleading outputs;
- rewrite or replace broken cells instead of leaving confusing execution history;
- manage kernel state deliberately so the notebook remains reproducible.

## Core Workflow

1. **Choose a kernel**
   - If the user did not specify a kernel, use `jupytercode_kernel_selection` guidance.
   - Match code language to kernel language: Python code to Python kernel, R code to R kernel.
   - Prefer an environment where required packages are already installed.
   - Do not install packages unless the user explicitly approves.

2. **Open or create a notebook**
   - Use `jupytercode_use_notebook` before any notebook read/write/execute operation.
   - Use stable, concrete and detailed notebook names such as `xxx_analysis`, `xxx_scrna_analysis`, or a user-provided name.
   - Use meaningful notebook paths, preferably under the current project or output directory.

3. **Inspect before changing**
   - Use `jupytercode_notebooks_info` to see existing sessions when session names are uncertain.
   - Use `jupytercode_read_notebook` before deciding where to insert, overwrite, or delete cells.
   - Use `jupytercode_read_cell` when a specific cell's full source or output matters.

4. **Write code as notebook cells**
   - Use `jupytercode_insert_execute_code_cell` for normal iterative analysis.
   - Use `jupytercode_insert_cell` for markdown notes, explanations, section headers, or code drafts that should not run yet.
   - Prefer clear, self-contained cells with imports, parameters, paths, and concise progress messages.

5. **Handle errors deliberately**
   - If execution fails, read the error output and fix the cause before retrying.
   - Prefer `jupytercode_overwrite_cell_source` when the existing cell's intent is still valid but the code needs correction.
   - Use `jupytercode_delete_cell` for disposable failed attempts, duplicate code, temporary debugging, or misleading cells after confirming the target index.
   - Do not leave failed exploratory code in the final notebook unless it is scientifically important evidence.

6. **Manage execution state**
   - Use `jupytercode_session_control(action="status")` to inspect kernel liveness, running cells, and last execution state.
   - Use `action="interrupt"` for code that is clearly stuck or no longer needed.
   - Use `action="restart"` only when kernel state is corrupted or a clean state is required.
   - Use `action="shutdown"` when the notebook session is no longer needed.

## Tool Selection Rules

Use these tools as the main Jupytercode surface:

- `jupytercode_kernel_selection`: decide which kernel is appropriate.
- `jupytercode_notebooks_info`: list currently registered notebook sessions.
- `jupytercode_use_notebook`: open/create a notebook session.
- `jupytercode_read_notebook`: inspect notebook structure and cell previews.
- `jupytercode_read_cell`: inspect one cell in full.
- `jupytercode_insert_cell`: insert markdown or non-executed code.
- `jupytercode_insert_execute_code_cell`: insert and execute a new code cell.
- `jupytercode_overwrite_cell_source`: replace one cell's source without executing it.
- `jupytercode_delete_cell`: delete a confirmed unwanted cell.
- `jupytercode_session_control`: status, interrupt, restart, or shutdown.

Do not call unregistered compatibility helpers directly unless they have been explicitly exposed by the runtime.

## Timeout Policy

Jupyter execution tools use `timeout_seconds`.

- Default timeout is suitable for most interactive analysis.
- Use `timeout_seconds=0` only when the user expects intentionally long-running code.
- Before using an unlimited timeout, make sure the code has useful progress logging or writes intermediate outputs.
- If code times out, inspect the partial output and kernel status before retrying.

## Notebook Hygiene

Keep the final notebook useful for later inspection and execution:

- Add short markdown section headers for major workflow phases.
- Arrange cells in logical execution order.
- Keep setup, loading, preprocessing, analysis, visualization, and output-writing steps clearly separated.
- Keep code cells focused on one analysis step.
- Print concise summaries after loading data, filtering, fitting models, or writing outputs.
- Save important outputs to explicit paths.
- Avoid hidden global assumptions; define paths, parameters, seeds, and output directories visibly.
- Delete or overwrite failed code cells that are not useful for the final narrative.
- Do not delete cells that contain important provenance, results, user-authored content, or scientifically meaningful diagnostics.

Before considering notebook work complete, inspect the notebook and clean it:

1. Confirm the notebook reads as a coherent workflow from top to bottom.
2. Remove temporary scratch cells and duplicate failed attempts.
3. Overwrite broken cells when the intended step should remain.
4. Keep only diagnostics that explain important decisions or quality control.
5. Ensure final outputs, saved files, and key results are visible.

## Bioinformatics Coding Practices

For scientific analysis code:

- Verify input files exist before loading.
- Preserve sample, cell, gene, and feature identifiers.
- Print object dimensions and key metadata columns after loading.
- Record package versions when results depend on package behavior.
- Set random seeds for stochastic steps.
- Save intermediate artifacts when later steps may reuse them.
- Avoid overwriting user data unless the user requested it.

## Recovery Patterns

When a cell fails:

1. Read the failed cell and output.
2. Identify whether the issue is code syntax, missing package, missing file, wrong object state, or wrong kernel.
3. If the cell's intent is valid, overwrite the cell source with corrected code.
4. Insert and execute a new diagnostic cell only when needed.
5. Delete failed exploratory cells if they add no useful provenance or would confuse the final notebook.

When kernel state is confusing:

1. Use `jupytercode_session_control(action="status")`.
2. If a cell is stuck, use `action="interrupt"`.
3. If state is polluted or inconsistent, explain the consequence and use `action="restart"`.
4. After restart, rerun or recreate required setup cells before downstream analysis.

## Response Style

When reporting notebook work to the user, mention:

- notebook session name;
- notebook path;
- whether execution succeeded;
- whether the notebook was cleaned into a coherent final workflow;
- key output summaries;
- any remaining errors or required user decisions.

Do not paste long notebook outputs into the final response. Summarize them and point to the notebook.
