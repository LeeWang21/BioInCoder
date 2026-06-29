# BioInCoder

BioInCoder is a lightweight multi-agent assistant for biology, bioinformatics,
biomedical literature work, and reproducible coding.

It is built on LangChain/LangGraph and provides:

- a main coordinating agent: `BioInCoder`
- specialized subagents for planning, academic search, browser work, and local
  document reading
- project skills under `skills/` for single-cell, ATAC-seq, literature mining,
  browser workflows, and notebook-backed analysis
- Jupyter notebook tools for traceable code execution

## Project Layout

```text
Run.py                 CLI entry point
AgentConfigSetup.py    agent, tool, middleware, and runtime registration
AgentConfig.py         agent config and registry abstractions
Runtime.py             multi-agent runtime and message handoff helpers
Prompts.py             system prompts for BioInCoder and subagents
Skill*.py              skill loading, registry, and tool integration
*_tools.py             tool implementations for search, browser, read, plans, etc.
jupytercode_tool.py    notebook/session/kernel execution tools
skills/                domain and workflow skill packages
```

## Requirements

- Python 3.10+
- `DEEPSEEK_API_KEY`
- Python dependencies in `requirements.txt`

Optional runtime tools depend on the workflow:

- `markitdown` for document reading
- `agent-browser` and `cloakbrowser` for browser automation
- Jupyter kernels and bioinformatics packages for notebook-backed analysis

## Setup

```bash
./setup_bioincoder_env.sh
export DEEPSEEK_API_KEY="<your-key>"
```

If your default `python3` is older than 3.10, set:

```bash
export BIOINCODER_PYTHON=/path/to/python3.10+
```

## Run

```bash
./run_bioincoder.sh --user-id user1
```

Useful options:

```bash
./run_bioincoder.sh --user-id user1 --session-id literature-task-001
```

`user-id` is required unless `BIOINCODER_USER_ID` is set in the environment.
If `session-id` is not provided and `BIOINCODER_SESSION_ID` is not set,
BioInCoder creates a new session id automatically and prints a resume command.

BioInCoder also has a unified CLI entry point:

```bash
python3 bioincoder_cli.py run --user-id user1
python3 bioincoder_cli.py run --user-id user1 --session-id literature-task-001
python3 bioincoder_cli.py skills validate
python3 bioincoder_cli.py sessions list
python3 bioincoder_cli.py transcript show --user-id user1 --session-id literature-task-001 --limit 50
python3 bioincoder_cli.py transcript path --user-id user1 --session-id literature-task-001
python3 bioincoder_cli.py transcript subagents --user-id user1 --session-id literature-task-001
```

The `run` command starts the interactive REPL and requires `DEEPSEEK_API_KEY`.
Offline maintenance commands such as `skills validate` and `sessions list` do
not initialize the model runtime.

Inside the REPL, use `/transcript` or `/transcript show [n]` to show recent
main conversation entries, `/transcript path` to print the main transcript
path, `/transcript subagents` to list saved subagent transcripts, and
`/transcript subagent <channel> <request_id>` to read one subagent transcript.

`session-id` is the restart key. Start BioInCoder again with the same
`user-id` and `session-id` to continue the same session when SQLite
checkpointing is installed.

Use `/exit` or Ctrl-D to quit.

Runtime state is stored under `artifacts/` by default:

- `artifacts/checkpoints/bioincoder.sqlite` for LangGraph checkpoints
- `artifacts/sessions/<user-id>/<session-id>/transcript.jsonl` for the main conversation transcript
- `artifacts/sessions/<user-id>/<session-id>/subagent_transcripts/` for saved subagent transcripts

Set `BIOINCODER_CHECKPOINTER=memory` to disable persistent checkpoints.

## Skills

Skills are loaded from `skills/**/SKILL.md`. Each skill contains frontmatter
metadata plus Markdown instructions. Agent-specific skills can set
`metadata.intended_agent` to control visibility.

Validate skill metadata with:

```bash
python3 validate_skills.py
```

Current skill areas include:

- academic search
- browser workflows
- local document reading
- Jupyter-backed coding
- literature evidence mining
- single-cell workflows
- ATAC-seq workflows

## Notes

This project is currently an interactive CLI-first prototype. Main-agent
checkpoints and saved subagent transcripts can persist across restarts when the
SQLite checkpoint dependency is installed. Jupyter kernels and some live
browser state are still process-local unless explicitly saved by a tool.
