from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any, Iterator


class EffectStore:
    """Persistent idempotency and approval-consumption store for simulated MCP effects."""

    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._setup()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _setup(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS effects (
                    idempotency_key TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    approval_id TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS consumed_approvals (
                    approval_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL,
                    consumed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def get(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM effects WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return json.loads(row["result_json"]) if row is not None else None

    def get_consumed_approval(self, approval_id: str) -> str | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT idempotency_key FROM consumed_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        return str(row["idempotency_key"]) if row is not None else None

    def commit_effect(
        self,
        *,
        idempotency_key: str,
        incident_id: str,
        tool_name: str,
        approval_id: str,
        result: dict[str, Any],
    ) -> None:
        """Record the effect and consume the approval atomically."""
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT idempotency_key FROM consumed_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if prior is not None and prior["idempotency_key"] != idempotency_key:
                connection.rollback()
                raise ValueError("APPROVAL_ALREADY_CONSUMED")
            connection.execute(
                """
                INSERT OR IGNORE INTO effects(
                    idempotency_key, incident_id, tool_name, approval_id, result_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    incident_id,
                    tool_name,
                    approval_id,
                    json.dumps(result, sort_keys=True),
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO consumed_approvals(approval_id, idempotency_key)
                VALUES (?, ?)
                """,
                (approval_id, idempotency_key),
            )
            connection.commit()

    def clear(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("DELETE FROM effects")
            connection.execute("DELETE FROM consumed_approvals")
            connection.commit()
