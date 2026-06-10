#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is not set."
  echo "Run: export DEEPSEEK_API_KEY='<your-key>'"
  exit 1
fi

export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

PYTHON_BIN="${BIOINCODER_PYTHON:-python3}"

"$PYTHON_BIN" inspect_browser_runtime.py
