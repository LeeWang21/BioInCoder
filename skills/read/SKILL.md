---
name: bioincoder-read
description: Use BioInCoder ReadAgent with MarkItDown for quick local document reading of PDFs, Word, Excel, PowerPoint, HTML, CSV/TSV, JSON/XML, and downloaded supplementary files. Use when converting documents to Markdown, searching converted text, or extracting targeted snippets with low context.
metadata:
  tool_type: read
  primary_tool: markitdown_command
---

# BioInCoder Read

Use this skill when ReadAgent needs to inspect a local document artifact with MarkItDown.

The goal is not to dump the whole document. The goal is to answer the reading objective with the fewest conversion calls and the least returned context.

## Runtime Configuration

On the server, configure this environment variable if needed:

- `BIOINCODER_MARKITDOWN_BIN`: MarkItDown binary name or path. Default: `markitdown`.

## Core Workflow

Start small:

```json
{
  "source": "artifacts/browser/downloads/example.pdf",
  "pipe_commands": [["head", "-n", "80"]],
  "max_output_chars": 12000
}
```

For targeted questions, search converted Markdown:

```json
{
  "source": "artifacts/browser/downloads/example.xlsx",
  "pipe_commands": [["grep", "-i", "-E", "RAM|runtime|memory|scalability"]],
  "max_output_chars": 16000
}
```

For large files, prefer a safe stdout pipeline before returning text:

```json
{
  "source": "artifacts/browser/downloads/example.xlsx",
  "pipe_commands": [["grep", "-i", "RAM"], ["head", "-n", "120"]],
  "save_output": true,
  "output_name": "ram_lines.md",
  "max_output_chars": 16000
}
```

This is equivalent in spirit to:

```bash
markitdown example.xlsx | grep -i RAM | head -n 120
```

but it is executed without an arbitrary shell. Allowed pipe commands are `grep`, `head`, `tail`, `sed`, `wc`, `rg`, `cut`, `sort`, and `uniq`.

These safe pipe commands are useful for document triage:

- `rg`: fast regex search from stdin, e.g. `[["rg", "-i", "-n", "RAM|runtime"]]`;
- `sed`: read a line range after locating line numbers, e.g. `[["sed", "-n", "120,180p"]]`;
- `wc`: count lines/words/bytes, e.g. `[["wc", "-l"]]`;
- `cut`: select characters or fields, e.g. `[["cut", "-c", "1-160"]]`;
- `sort`: sort lines, e.g. `[["sort", "-u"]]`;
- `uniq`: collapse repeated adjacent lines, e.g. `[["sort"], ["uniq", "-c"]]`.

Typical large-document workflow:

```json
{
  "source": "artifacts/browser/downloads/example.xlsx",
  "pipe_commands": [["grep", "-n", "-i", "RAM"]],
  "max_output_chars": 12000
}
```

Then read a nearby range:

```json
{
  "source": "artifacts/browser/downloads/example.xlsx",
  "pipe_commands": [["sed", "-n", "180,240p"]],
  "max_output_chars": 16000
}
```

Save the full conversion when useful:

```json
{
  "source": "artifacts/browser/downloads/example.docx",
  "save_output": true,
  "output_name": "example.md",
  "max_output_chars": 12000
}
```

`markitdown_command` returns:

- `stdout`: filtered Markdown for the agent to read;
- `output_path`: full converted Markdown path when saved;
- `pipe_commands`: any safe stdout pipeline applied after MarkItDown;
- `line_stats`: line counts after any pipe_commands;
- `stderr`: conversion warnings or errors.

## Reading Rules

- Use `pipe_commands` and `max_output_chars` before returning large text.
- For large files, prefer `pipe_commands` to reduce stdout before it reaches the agent context.
- Search for user-requested keywords, tables, metrics, section names, sheet labels, figure labels, and supplement labels first.
- Report `output_path` so BioInCoder can trace the converted artifact.
- If MarkItDown output is too lossy for a precise answer, say so and recommend a deeper specialized reader.
- For Excel workbooks, MarkItDown is a quick first pass. Do not claim complete sheet-level inspection unless the converted output exposes enough structure.
- For PDFs, MarkItDown is a quick first pass. Do not claim precise page-level evidence unless page information is present in the output.

## Output

Return concise Markdown:

## Read Summary
State which file was read and how.

## Findings
Answer the user's objective with extracted evidence.

## Artifacts
List converted Markdown paths.

## Notes / Limitations
Mention truncation, missing structure, conversion limits, or need for a deeper reader.
