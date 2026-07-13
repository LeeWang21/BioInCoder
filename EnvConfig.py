from __future__ import annotations

import os
import re
from pathlib import Path


_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_inline_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for idx, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "#" and (idx == 0 or value[idx - 1].isspace()):
            return value[:idx].rstrip()
    return value.strip()


def _parse_env_value(raw: str) -> str:
    value = _strip_inline_comment(raw.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    if "\\" in value:
        value = value.replace("\\n", "\n").replace("\\t", "\t")
    return value


def load_env_file(path: str | os.PathLike[str] | None = None, *, override: bool = False) -> Path | None:
    """Load simple KEY=VALUE pairs from a local .env file.

    Existing process environment values win by default. The parser intentionally
    supports only dotenv-style assignments, not shell execution.
    """

    raw_path = path or os.environ.get("BIOINCODER_ENV_FILE") or ".env"
    env_path = Path(raw_path).expanduser()
    if not env_path.is_absolute():
        env_path = (Path.cwd() / env_path).resolve()
    if not env_path.exists():
        return None

    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"Invalid .env line {line_number}: expected KEY=VALUE.")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY_RE.match(key):
            raise ValueError(f"Invalid .env key on line {line_number}: {key!r}.")
        if not override and key in os.environ:
            continue
        os.environ[key] = _parse_env_value(raw_value)

    return env_path
