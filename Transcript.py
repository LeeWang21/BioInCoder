from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from Persistence import session_root, session_subagent_transcripts_dir


DEFAULT_HISTORY_LIMIT = 20


def transcript_path(user_id: str, session_id: str) -> Path:
    return session_root(user_id, session_id) / "transcript.jsonl"


def subagent_transcripts_dir(user_id: str, session_id: str) -> Path:
    return session_subagent_transcripts_dir(user_id, session_id)


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


def list_subagent_transcript_refs(user_id: str, session_id: str) -> dict[str, list[str]]:
    root = subagent_transcripts_dir(user_id, session_id)
    refs: dict[str, list[str]] = {}
    if not root.exists():
        return refs

    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        channel_name = payload.get("channel_name")
        request_id = payload.get("request_id")
        if not channel_name or not request_id:
            continue
        refs.setdefault(str(channel_name), []).append(str(request_id))
    return refs


def format_subagent_transcript_refs(refs: dict[str, list[str]]) -> str:
    if not refs:
        return "(no subagent transcripts)"

    lines: list[str] = []
    for channel_name in sorted(refs):
        lines.append(f"{channel_name}")
        for request_id in sorted(refs[channel_name]):
            lines.append(f"  - {request_id}")
    return "\n".join(lines)


def _safe_file_component(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-")
    return safe or "unnamed"


def subagent_transcript_file_path(user_id: str, session_id: str, channel_name: str, request_id: str) -> Path:
    filename = f"{_safe_file_component(channel_name)}__{_safe_file_component(request_id)}.json"
    return subagent_transcripts_dir(user_id, session_id) / filename


def read_subagent_transcript_payload(
    user_id: str,
    session_id: str,
    channel_name: str,
    request_id: str,
) -> dict[str, Any]:
    path = subagent_transcript_file_path(user_id, session_id, channel_name, request_id)
    if not path.exists():
        raise FileNotFoundError(f"Subagent transcript does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _message_role(message: dict[str, Any]) -> str:
    role = message.get("type") or message.get("role")
    if role:
        return str(role)
    data = message.get("data")
    if isinstance(data, dict):
        role = data.get("type") or data.get("role")
        if role:
            return str(role)
    return "message"


def _message_content(message: dict[str, Any]) -> str:
    data = message.get("data")
    if isinstance(data, dict) and "content" in data:
        return str(data.get("content") or "")
    if "content" in message:
        return str(message.get("content") or "")
    return json.dumps(message, ensure_ascii=False, indent=2, default=str)


def format_subagent_transcript_payload(payload: dict[str, Any], output_format: str = "prefix") -> str:
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if output_format != "prefix":
        raise ValueError("Subagent transcript format must be 'prefix' or 'json'.")

    header = (
        f"Subagent transcript: {payload.get('channel_name')} / {payload.get('request_id')}\n"
        f"user_id={payload.get('user_id')} session_id={payload.get('session_id')}"
    )
    lines = [header]
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            lines.append(f"\nmessage\n{message}")
            continue
        role = _message_role(message)
        content = _message_content(message)
        lines.append(f"\n{role}\n{content}")
    return "\n".join(lines)
