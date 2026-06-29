from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from Persistence import session_root


DEFAULT_HISTORY_LIMIT = 20


def transcript_path(user_id: str, session_id: str) -> Path:
    return session_root(user_id, session_id) / "transcript.jsonl"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class TranscriptStore:
    user_id: str
    session_id: str
    path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.path = transcript_path(self.user_id, self.session_id)

    def append(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        if content is None:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _now_iso(),
            "role": role,
            "content": str(content),
            "metadata": metadata or {},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())

    def read_entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        entries: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    entry = {
                        "ts": "",
                        "role": "system",
                        "content": f"[invalid transcript JSON at line {line_number}]",
                        "metadata": {},
                    }
                entries.append(entry)
        return entries

    def read_recent(self, limit: int = DEFAULT_HISTORY_LIMIT) -> list[dict[str, Any]]:
        limit = max(1, limit)
        entries = self.read_entries()
        return entries[-limit:]


def format_entry(entry: dict[str, Any]) -> str:
    ts = entry.get("ts") or "unknown-time"
    role = entry.get("role") or "unknown"
    content = str(entry.get("content") or "")
    return f"[{ts}] {role}\n{content}"


def format_entries(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "(no transcript entries)"
    return "\n\n".join(format_entry(entry) for entry in entries)
