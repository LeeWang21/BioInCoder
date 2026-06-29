from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from datetime import datetime
from uuid import uuid4


def safe_id(value: str | None, default: str) -> str:
    raw = (value or default).strip() or default
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return safe or default


def artifacts_root() -> Path:
    return Path(os.environ.get("BIOINCODER_ARTIFACTS_DIR", "artifacts")).resolve()


def session_root(user_id: str, session_id: str) -> Path:
    return artifacts_root() / "sessions" / safe_id(user_id, "default_user") / safe_id(session_id, "default_session")


def session_subagent_transcripts_dir(user_id: str, session_id: str) -> Path:
    return session_root(user_id, session_id) / "subagent_transcripts"


def generate_session_id() -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid4().hex[:4]}"


def checkpoint_db_path() -> Path:
    raw = os.environ.get("BIOINCODER_CHECKPOINT_DB")
    if raw:
        return Path(raw).expanduser().resolve()
    return artifacts_root() / "checkpoints" / "bioincoder.sqlite"


def graph_thread_id(user_id: str, session_id: str, thread_id: str | None = None) -> str:
    if thread_id and thread_id.strip():
        return f"{safe_id(user_id, 'default_user')}:{safe_id(session_id, 'default_session')}:{safe_id(thread_id, 'main')}"
    return f"{safe_id(user_id, 'default_user')}:{safe_id(session_id, 'default_session')}"


def make_checkpointer() -> Any:
    backend = os.environ.get("BIOINCODER_CHECKPOINTER", "sqlite").strip().lower()
    if backend in {"memory", "inmemory", "in_memory"}:
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        from langgraph.checkpoint.memory import InMemorySaver

        print(
            "Warning: langgraph-checkpoint-sqlite is not installed; "
            "falling back to process-local InMemorySaver. "
            "Install langgraph-checkpoint-sqlite for restart support."
        )
        if os.environ.get("BIOINCODER_REQUIRE_PERSISTENCE") == "1":
            raise RuntimeError("Persistent checkpointing is required but unavailable.") from exc
        return InMemorySaver()

    path = checkpoint_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        checkpointer = SqliteSaver(conn)
    except TypeError:
        conn.close()
        context = SqliteSaver.from_conn_string(str(path))
        checkpointer = context.__enter__()
        setattr(checkpointer, "_bioincoder_sqlite_context", context)
    setup = getattr(checkpointer, "setup", None)
    if callable(setup):
        setup()
    return checkpointer
