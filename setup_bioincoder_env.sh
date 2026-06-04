#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${BIOINCODER_PYTHON:-python3}"

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit(
        "BioInCoder requires Python >= 3.10 for the current LangChain/LangGraph stack. "
        f"Current Python is {sys.version.split()[0]}. "
        "Set BIOINCODER_PYTHON=/path/to/python3.10+ and rerun this script."
    )
PY

"$PYTHON_BIN" -m pip install -r requirements.txt
