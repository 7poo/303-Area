"""Small, auditable memory store for agent sessions and user preferences."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_security import redact_secrets


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    """SQLite-backed short-term and explicit long-term memory.

    Retrieval is deliberately lexical and bounded for the MVP.  The schema has
    room for an embedding reference later without coupling the core agent to a
    vector database.
    """

    def __init__(self, path: str = "./warehouse/agent_memory.sqlite") -> None:
        self.path = str(Path(path))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant','tool')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_messages_session
                    ON agent_messages(user_id, session_id, id);
                CREATE TABLE IF NOT EXISTS agent_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    embedding_ref TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_memories_user
                    ON agent_memories(user_id, created_at);
                CREATE TABLE IF NOT EXISTS agent_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    route TEXT NOT NULL,
                    model TEXT,
                    trace_json TEXT NOT NULL,
                    safety_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_traces_user
                    ON agent_traces(user_id, created_at);
            """)

    def append_message(self, user_id: str, session_id: str, role: str, content: str) -> None:
        safe = redact_secrets(content or "")[:12000]
        with self._db() as conn:
            conn.execute(
                "INSERT INTO agent_messages(user_id,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
                (user_id, session_id, role, safe, _now()),
            )

    def recent_messages(self, user_id: str, session_id: str, limit: int = 8) -> list[dict[str, str]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT role,content,created_at FROM agent_messages "
                "WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT ?",
                (user_id, session_id, max(1, min(limit, 20))),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def add_memory(self, user_id: str, content: str, kind: str = "preference", source: str = "user") -> int:
        safe = redact_secrets(content or "")[:4000]
        with self._db() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_memories(user_id,kind,content,source,created_at) VALUES(?,?,?,?,?)",
                (user_id, kind, safe, source[:80], _now()),
            )
            return int(cursor.lastrowid)

    def search(self, user_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        tokens = {token for token in re.findall(r"[\wÀ-ỹ]{3,}", query.lower())}
        if not tokens:
            return []
        with self._db() as conn:
            rows = conn.execute(
                "SELECT id,kind,content,source,created_at FROM agent_memories "
                "WHERE user_id=? ORDER BY id DESC LIMIT 100",
                (user_id,),
            ).fetchall()
        scored = []
        for row in rows:
            text = row["content"].lower()
            score = sum(1 for token in tokens if token in text)
            if score:
                item = dict(row)
                item["score"] = score
                scored.append(item)
        scored.sort(key=lambda item: (item["score"], item["id"]), reverse=True)
        return scored[: max(1, min(limit, 10))]

    def append_trace(
        self,
        request_id: str,
        user_id: str,
        session_id: str,
        route: str,
        model: str | None,
        trace: list[dict[str, Any]],
        safety: dict[str, Any],
    ) -> None:
        import json

        with self._db() as conn:
            conn.execute(
                "INSERT INTO agent_traces(request_id,user_id,session_id,route,model,trace_json,safety_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    request_id, user_id, session_id, route, model,
                    json.dumps(trace, ensure_ascii=False, default=str)[:20000],
                    json.dumps(safety, ensure_ascii=False, default=str)[:8000],
                    _now(),
                ),
            )
