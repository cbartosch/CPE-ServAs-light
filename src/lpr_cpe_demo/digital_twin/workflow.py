# ruff: noqa: E501
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import HumanDecision


def _now(at: str | None = None) -> str:
    return at or datetime.now(UTC).isoformat()


class CaseStore:
    """Durable case bridge. Effects are simulation-only; production writes do not exist."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    eligible_actions TEXT NOT NULL,
                    proposed_action TEXT NOT NULL,
                    human_decision TEXT,
                    simulated_effect TEXT,
                    updated_at TEXT NOT NULL
                )"""
            )

    @contextmanager
    def _connect(self):
        """Open a short-lived SQLite connection and always close it.

        sqlite3.Connection's context-manager protocol commits/rolls back but
        does not close the connection. On Windows that can leave control.sqlite
        locked long enough to make the run-directory publish (os.replace) fail.
        """
        con = sqlite3.connect(self.db_path)
        try:
            with con:
                yield con
        finally:
            con.close()

    def create_case(
        self,
        case_id: str,
        proposed_action: str,
        eligible_actions: list[str],
        human_review_required: bool,
        at: str | None = None,
    ) -> dict:
        state = "WAITING_HUMAN" if human_review_required else "READY_AUTO"
        with self._connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO cases VALUES (?,?,?,?,?,?,?,?)",
                (case_id, 1, state, json.dumps(eligible_actions), proposed_action, None, None, _now(at)),
            )
        return self.get(case_id)

    def create_pending(self, case_id: str, proposed_action: str, eligible_actions: list[str], at: str | None = None) -> dict:
        return self.create_case(case_id, proposed_action, eligible_actions, True, at=at)

    def get(self, case_id: str) -> dict:
        with self._connect() as con:
            row = con.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        keys = ["case_id", "revision", "state", "eligible_actions", "proposed_action", "human_decision", "simulated_effect", "updated_at"]
        data = dict(zip(keys, row, strict=True))
        data["eligible_actions"] = json.loads(data["eligible_actions"])
        if data["human_decision"]:
            data["human_decision"] = json.loads(data["human_decision"])
        if data["simulated_effect"]:
            data["simulated_effect"] = json.loads(data["simulated_effect"])
        return data

    def decide(self, decision: HumanDecision, at: str | None = None) -> dict:
        current = self.get(decision.case_id)
        if current["state"] != "WAITING_HUMAN":
            raise ValueError("case is not waiting for human review")
        if current["revision"] != decision.revision:
            raise ValueError("stale decision revision")
        human = decision.model_dump()
        effect = None
        if decision.response == "approve":
            if current["proposed_action"] not in current["eligible_actions"]:
                raise ValueError("proposed action is not eligible")
            state = "ACTION_SIMULATED"
            effect = {
                "action": current["proposed_action"],
                "outcome": "SIMULATED",
                "production_write": False,
                "idempotency_key": f"{decision.case_id}:{decision.revision}:{current['proposed_action']}",
            }
        elif decision.response == "request_evidence":
            state = "NEEDS_EVIDENCE"
        else:
            state = "ESCALATED"
        with self._connect() as con:
            updated = con.execute(
                """UPDATE cases SET revision=?, state=?, human_decision=?, simulated_effect=?, updated_at=?
                   WHERE case_id=? AND revision=? AND state='WAITING_HUMAN'""",
                (
                    decision.revision + 1,
                    state,
                    json.dumps(human),
                    json.dumps(effect) if effect else None,
                    _now(at),
                    decision.case_id,
                    decision.revision,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("concurrent or stale case update")
        return self.get(decision.case_id)

    def auto_execute(self, case_id: str, rationale: str, at: str | None = None) -> dict:
        current = self.get(case_id)
        if current["state"] != "READY_AUTO":
            raise ValueError("case is not eligible for automatic execution")
        if current["proposed_action"] not in current["eligible_actions"]:
            raise ValueError("proposed action is not eligible")
        effect = {
            "action": current["proposed_action"],
            "outcome": "SIMULATED",
            "production_write": False,
            "authorization": "POLICY_AUTO",
            "rationale": rationale,
            "idempotency_key": f"{case_id}:{current['revision']}:{current['proposed_action']}",
        }
        with self._connect() as con:
            updated = con.execute(
                """UPDATE cases SET revision=?, state='ACTION_SIMULATED', simulated_effect=?, updated_at=?
                   WHERE case_id=? AND revision=? AND state='READY_AUTO'""",
                (current["revision"] + 1, json.dumps(effect), _now(at), case_id, current["revision"]),
            )
            if updated.rowcount != 1:
                raise ValueError("concurrent or stale case update")
        return self.get(case_id)

    def mark_verified(self, case_id: str, at: str | None = None) -> dict:
        current = self.get(case_id)
        if current["state"] != "ACTION_SIMULATED":
            raise ValueError("case has no simulated action to verify")
        with self._connect() as con:
            updated = con.execute(
                """UPDATE cases SET revision=?, state='CLOSED_SIMULATED', updated_at=?
                   WHERE case_id=? AND revision=? AND state='ACTION_SIMULATED'""",
                (current["revision"] + 1, _now(at), case_id, current["revision"]),
            )
            if updated.rowcount != 1:
                raise ValueError("concurrent or stale case update")
        return self.get(case_id)
