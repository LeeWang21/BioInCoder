---
name: bioincoder-code-review
description: Review generated or modified code deliverables for correctness, reproducibility, runnable validation, and alignment with the user's stated intent. Use for notebooks, Python/R/shell scripts, workflow files, and analysis deliverables before BioInCoder finalizes non-trivial code work.
metadata:
  tool_type: review
  primary_tools:
    - code_review
    - code_review_workspace
  intended_agent: [BioInCoder, CodeReviewer, planner]
---

# BioInCoder Code Review

Use this skill when code, notebooks, scripts, workflow files, or analysis
deliverables need independent review before handoff.

BioInCoder is the author and coordinator. CodeReviewer is the independent
reviewer. The review workspace tool provides isolated file inspection, command
execution, and notebook-copy execution evidence.

## Review Boundary

Code review must be read-only by default.

Do not modify original source files, notebooks, formal outputs, caches, or
active Jupyter sessions during review. Do not restart, interrupt, overwrite,
delete, or append cells in an author's active notebook session.

If execution is needed, use `code_review_workspace` to operate on isolated
copies. If a requested check would mutate original artifacts, report that it
requires explicit approval.

## What To Review

Review both implementation mechanics and task intent:

- runnable correctness: syntax, imports, entrypoints, obvious runtime hazards;
- reproducibility: explicit inputs, outputs, seeds, environment assumptions,
  checkpointing, and hidden notebook state;
- intent alignment: whether the code implements the user's stated goal and
  requested outputs;
- deliverability: whether notebooks, scripts, README commands, requirements,
  outputs, and checkpoint artifacts form a coherent handoff.

## BioInCoder Usage

BioInCoder should call `code_review` for non-trivial generated or modified
runnable code, especially when the task:

- creates or edits a notebook, analysis script, shell script, or workflow;
- affects scientific or computational correctness;
- involves input/output paths, checkpoints, or cached intermediates;
- produces a user-facing deliverable;
- is explicitly requested for review.

The `code_review` task brief must be detailed and self-contained because
CodeReviewer does not receive the full main conversation. Include:

- overall user goal;
- current code change or generated deliverable;
- target files and exact in-scope sections, functions, or notebook cells;
- expected inputs, outputs, figures, tables, and saved artifacts;
- runtime constraints and expensive stages;
- available checkpoints or resume expectations;
- what counts as blocking;
- what is explicitly out of scope.

Use `mode="fast"` for small or static reviews, `mode="resume"` for notebook or
bioinformatics analysis deliverables that should recover from checkpoints, and
`mode="full"` only when a full clean execution is feasible or explicitly needed.

## Authoring For Review

BioInCoder should write code so CodeReviewer can evaluate it from files and
artifacts, without relying on hidden conversation state or a live kernel.

For all runnable code:

- make inputs, outputs, parameters, assumptions, and side effects explicit;
- avoid hard-coded absolute paths unless the user provided them;
- create output directories before writing;
- save requested results to files, not only to console/notebook display;
- print concise progress and output summaries for long-running workflows;
- preserve sample, cell, gene, feature, and group identifiers;
- set random seeds for stochastic algorithms;
- keep expensive steps checkpointed or restartable when practical;
- make failure modes explicit with clear errors for missing inputs or invalid
  metadata columns;
- avoid destructive writes to user data unless explicitly requested.

For scripts:

- provide a clear entrypoint (`main()` for Python when practical);
- expose input/output paths and major options through CLI arguments or a visible
  configuration block;
- support `--help` or an equivalent usage path when feasible;
- keep reusable logic in functions rather than only top-level side effects;
- write logs or summaries for important generated artifacts.

For notebooks:

- use visible setup, path, parameter, seed, input-check, stage, checkpoint, and
  output-inventory cells;
- make downstream sections able to resume from saved checkpoints where expensive
  upstream work is involved;
- clean final notebooks so they are reviewable workflows rather than raw debug
  histories.

For shell/workflow files:

- define required inputs and outputs clearly;
- validate arguments before running expensive commands;
- quote variables and paths;
- use `set -euo pipefail` where appropriate;
- keep destructive commands guarded and scoped.

## CodeReviewer Workflow

1. Read the delegated task brief and target paths.
2. Load this skill if not already loaded.
3. Call `code_review_workspace(action="prepare")` with the delegated review id
   and target paths.
4. Use `action="list"` to inspect the copied workspace.
5. Use `action="read"` and `action="notebook_read"` to inspect in-scope code,
   notebook sections, outputs, checkpoints, and side effects.
6. Use `action="run"` for safe syntax, lint, help, or smoke commands inside the
   workspace when appropriate.
7. Use `action="notebook_info"` before notebook execution to check kernelspec
   metadata and available kernels.
8. Use `action="notebook_execute"` or `action="notebook_execute_range"` only on
   workspace notebook copies when execution is safe and relevant.
9. Compare the implementation against the task brief's user goal, expected
   outputs, and blocking criteria.
10. Report blocking issues first, then non-blocking issues and residual risk.

When `mode="resume"` or `mode="full"` asks for stronger validation but only
partial isolated execution is feasible, state exactly what was executed, what
was skipped, and why.

## Workspace Actions

Use `code_review_workspace` actions as follows:

- `prepare`: create `artifacts/code_review/<review_id>/workspace/` and copy
  target files/directories into it.
- `list`: inspect copied files and generated review outputs.
- `read`: read workspace text files; for `.ipynb`, returns a notebook summary.
- `run`: run a safe command in the workspace, with timeout and truncated output.
- `notebook_info`: inspect notebook metadata, kernelspec, language, available
  kernels, and recommended kernel.
- `notebook_read`: read notebook cells by markdown section title, source query,
  or inclusive cell index range.
- `notebook_execute`: execute a workspace notebook copy from top to bottom.
- `notebook_execute_range`: execute an inclusive cell range in a workspace
  notebook copy.
- `notebook_shutdown`: close review notebook sessions for this review id.

Notebook execution in `code_review_workspace` is implemented through
BioInCoder's existing `NotebookRegistry` / `NotebookSession` Jupyter machinery,
but with review-specific session names and workspace notebook copies. It must
not use the author's active `JUPYTER_REGISTRY` session or original notebook path.
The `code_review` wrapper also performs a best-effort shutdown of review
notebook sessions after CodeReviewer returns, so review kernels should not be
treated as persistent state.

Do not use ordinary Bash or author-facing Jupytercode tools for review.

## Notebook Review Procedure

For notebook targets, use this procedure:

1. Prepare the review workspace.
   - Call `code_review_workspace(action="prepare")`.
   - Review only the copied notebook in the workspace.

2. Inspect notebook metadata.
   - Call `code_review_workspace(action="notebook_info")`.
   - Use the notebook's recorded `metadata.kernelspec.name` as the required
     execution kernel.
   - Do not silently switch to `python3`, `ir`, or another available kernel.
   - If the recorded kernel is missing or unavailable, do not execute the
     notebook. Report execution as not verified and explain the residual risk.

3. Inspect the relevant notebook content.
   - Use `notebook_read` with `section` when the task brief names a section.
   - Use `notebook_read` with `cell_start` and `cell_end` when the task brief
     names a cell range.
   - Use `notebook_read` with `query` to find functions, variables, output
     writes, checkpoint paths, or analysis calls.
   - For complete deliverables, inspect setup, input validation, expensive
     stages, checkpoint loading/saving, downstream analysis, and output
     inventory sections.

4. Decide execution scope.
   - Use static review only for `mode="fast"` or when execution would be too
     expensive.
   - Use `notebook_execute_range` for a bounded prefix or section-level check
     when the task brief asks for a specific part of the notebook.
   - Use `notebook_execute` for full notebook-copy execution only when the mode
     and runtime constraints justify it.

5. Interpret partial execution carefully.
   - A range execution validates only that range under the executed prior state.
   - If the range depends on earlier cells or checkpoints that were not executed
     or loaded, report the limitation.
   - For resume-style review, prefer ranges that include setup plus checkpoint
     loading cells before downstream cells.

6. Clean up review kernels.
   - Use `notebook_shutdown` when done with notebook execution.
   - The `code_review` wrapper also performs best-effort shutdown after the
     review returns, but do not rely on kernel state as a deliverable.

## Notebook Execution Actions

`notebook_execute` executes the whole workspace notebook copy from the first
cell to the last cell using the notebook-recorded metadata kernel. Use it for
full clean execution checks when feasible.

`notebook_execute_range` executes only an inclusive cell range from the workspace
notebook copy, also using the notebook-recorded metadata kernel. Use it for
bounded section/prefix/resume checks when full execution is too expensive or the
review scope is partial.

Both actions execute only the copied notebook in the review workspace. Neither
action may execute or mutate the original notebook or the author's active
Jupyter session.

## File-Type Expectations

For notebooks:

- check valid notebook JSON, error outputs, unexecuted cells, execution count
  disorder, section headers, input/output/cache hints, and hidden-state risk;
- use `notebook_info` to check kernel metadata before execution;
- use `notebook_read` to inspect specific sections, cell ranges, or source
  queries from the copied notebook;
- use `notebook_execute` or `notebook_execute_range` only on workspace copies;
- use `notebook_shutdown` after execution when the review no longer needs the
  kernel;
- do not execute or mutate the active/original notebook;
- treat failed cells, missing critical outputs, and hidden-state dependency as
  blocking when they affect the deliverable.

For Python:

- check `python -m py_compile`;
- run `ruff check` when available;
- look for missing entrypoints, hard-coded paths, missing output writes, and
  untested assumptions when relevant.

For R:

- check parseability with `Rscript` when available;
- look for missing library assumptions, seeds, input/output handling, and saved
  outputs.

For shell:

- check shell syntax with `bash -n`;
- run `shellcheck` when available;
- look for unsafe path handling, missing `set -euo pipefail`, unquoted variables,
  and destructive commands.

## Blocking Criteria

Treat an issue as blocking when it can make the deliverable wrong, incomplete,
unrunnable, irreproducible, or materially misaligned with the user request.

Common blocking issues:

- syntax errors or failed notebook cells in required code;
- missing required input checks or reliance on nonexistent files;
- hidden notebook-state dependency for final deliverables;
- requested outputs are not saved;
- notebook/script/code compares the wrong groups, samples, species, assay, or
  metadata fields relative to the task brief;
- expensive downstream analysis cannot resume from the stated checkpoint when
  resume behavior is part of the deliverable;
- code mutates or overwrites user data unexpectedly;
- README or usage command does not match actual files or parameters;
- validation target paths are missing.

Common non-blocking issues:

- optional linter warnings that do not affect behavior;
- minor naming or formatting inconsistencies;
- missing convenience summaries when core outputs are present;
- style improvements that do not affect correctness or reproducibility.

## Intent Alignment Review

CodeReviewer should explicitly compare the implementation to the user's stated
intent in the task brief.

Check:

- required analysis steps are present;
- requested files, tables, figures, and summaries are generated;
- group/sample/condition/species/assay assumptions match the request;
- filtering, normalization, model, contrast, or comparison choices are visible;
- notebook narrative and code agree;
- output paths and names are understandable for handoff.

If the task brief is too vague to judge intent, report that as residual risk and
review only the observable code behavior.

## Report Format

Return:

1. Verdict: `pass`, `needs_fixes`, or `blocked`.
2. Blocking issues: severity-ordered, with file/path evidence.
3. Non-blocking issues.
4. Intent alignment.
5. Validation evidence.
6. Residual risks.
7. Suggested fixes.

If no issues are found, say that clearly and still list what was not verified.
