"""Tests for the approval token and the effect store.

AUDIT GAP THIS CLOSES
---------------------
Both modules carry controls that were reported as verified earlier in this
project, on the strength of ad-hoc checks run at a prompt and never committed:

* the HMAC approval token, with ten forgery attempts rejected
* the effect store's first-write-wins idempotency and
  APPROVAL_ALREADY_CONSUMED on reuse

A control demonstrated once interactively is not a control that stays working.
Both modules are standard-library only, so there was no reason for the gap.

    PYTHONPATH=src python3 -m unittest tests.test_security_store -v
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.mcp_server.security import (ApprovalTokenError,  # noqa: E402
                                              create_approval_token,
                                              verify_approval_token)
from lpr_cpe_demo.mcp_server.store import EffectStore  # noqa: E402

SECRET = "audit-secret"


def _claims(**overrides):
    base = {"approval_id": "apr-1", "incident_id": "INC-1",
            "action_type": "clean_boots", "idempotency_key": "idem-abc",
            "exp": time.time() + 600}
    base.update(overrides)
    return base


def _forge(token: str, mutate) -> str:
    """Tamper with the payload while keeping the original signature."""
    encoded, signature = token.split(".", 1)
    padded = encoded + "=" * (-len(encoded) % 4)
    raw = json.loads(base64.urlsafe_b64decode(padded))
    mutate(raw)
    payload = base64.urlsafe_b64encode(
        json.dumps(raw, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()
    return f"{payload}.{signature}"


class TestApprovalToken(unittest.TestCase):
    def test_valid_token_round_trips(self):
        claims = _claims()
        self.assertEqual(verify_approval_token(create_approval_token(claims, SECRET),
                                              SECRET), claims)

    def test_expiry_is_mandatory(self):
        no_exp = {k: v for k, v in _claims().items() if k != "exp"}
        with self.assertRaises(ApprovalTokenError) as ctx:
            verify_approval_token(create_approval_token(no_exp, SECRET), SECRET)
        self.assertIn("NO_EXPIRY", str(ctx.exception))

    def test_expired_token_is_refused(self):
        token = create_approval_token(_claims(exp=time.time() - 1), SECRET)
        with self.assertRaises(ApprovalTokenError) as ctx:
            verify_approval_token(token, SECRET)
        self.assertIn("EXPIRED", str(ctx.exception))

    def test_wrong_secret_is_refused(self):
        token = create_approval_token(_claims(), SECRET)
        with self.assertRaises(ApprovalTokenError):
            verify_approval_token(token, "not-the-secret")

    def test_malformed_token_is_refused(self):
        for bad in ("", "no-dot", "only.", ".onlysig", "a.b.c"):
            with self.assertRaises(ApprovalTokenError, msg=bad):
                verify_approval_token(bad, SECRET)

    def test_escalating_the_action_type_is_refused(self):
        """The forgery that matters: clean boots upgraded to plant work."""
        token = create_approval_token(_claims(), SECRET)
        forged = _forge(token, lambda r: r.update(action_type="dirty_boots_mr"))
        with self.assertRaises(ApprovalTokenError):
            verify_approval_token(forged, SECRET)

    def test_moving_the_approval_to_another_incident_is_refused(self):
        token = create_approval_token(_claims(), SECRET)
        forged = _forge(token, lambda r: r.update(incident_id="INC-999"))
        with self.assertRaises(ApprovalTokenError):
            verify_approval_token(forged, SECRET)

    def test_swapping_the_idempotency_key_is_refused(self):
        token = create_approval_token(_claims(), SECRET)
        forged = _forge(token, lambda r: r.update(idempotency_key="idem-other"))
        with self.assertRaises(ApprovalTokenError):
            verify_approval_token(forged, SECRET)

    def test_extending_the_expiry_is_refused(self):
        token = create_approval_token(_claims(), SECRET)
        forged = _forge(token, lambda r: r.update(exp=time.time() + 86_400))
        with self.assertRaises(ApprovalTokenError):
            verify_approval_token(forged, SECRET)

    def test_signature_is_not_a_plain_hash_of_the_payload(self):
        """A payload-only digest would let anyone mint a token."""
        import hashlib
        token = create_approval_token(_claims(), SECRET)
        encoded, signature = token.split(".", 1)
        naive = base64.urlsafe_b64encode(
            hashlib.sha256(encoded.encode()).digest()).rstrip(b"=").decode()
        self.assertNotEqual(signature, naive)


class TestEffectStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = EffectStore(pathlib.Path(self._tmp.name) / "effects.db")

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, key="idem-1", approval="apr-1", result=None):
        self.store.commit_effect(
            idempotency_key=key, incident_id="INC-1",
            tool_name="create_clean_boots_work_order", approval_id=approval,
            result=result or {"work_order_id": "WO-1"})

    def test_effect_is_retrievable_after_commit(self):
        self._commit()
        self.assertEqual(self.store.get("idem-1"),
                         {"work_order_id": "WO-1"})

    def test_unknown_key_returns_none_rather_than_raising(self):
        self.assertIsNone(self.store.get("never-seen"))

    def test_replay_with_the_same_key_is_a_no_op(self):
        """The control that stops one approval producing two work orders."""
        self._commit(result={"work_order_id": "WO-FIRST"})
        self._commit(result={"work_order_id": "WO-SECOND"})
        self.assertEqual(self.store.get("idem-1"),
                         {"work_order_id": "WO-FIRST"},
                         "first write must win; a replay must not overwrite")

    def test_reusing_an_approval_with_a_different_key_is_refused(self):
        """Replay and reuse are different things and must behave differently."""
        self._commit(key="idem-1", approval="apr-1")
        with self.assertRaises(ValueError) as ctx:
            self._commit(key="idem-2", approval="apr-1")
        self.assertIn("APPROVAL_ALREADY_CONSUMED", str(ctx.exception))

    def test_the_refused_reuse_leaves_no_partial_effect(self):
        self._commit(key="idem-1", approval="apr-1")
        with self.assertRaises(ValueError):
            self._commit(key="idem-2", approval="apr-1")
        self.assertIsNone(self.store.get("idem-2"),
                          "rolled back, so no orphan effect row")

    def test_distinct_approvals_are_independent(self):
        self._commit(key="idem-1", approval="apr-1")
        self._commit(key="idem-2", approval="apr-2",
                     result={"work_order_id": "WO-2"})
        self.assertEqual(self.store.get("idem-2"), {"work_order_id": "WO-2"})

    def test_consumed_approval_records_the_key_that_consumed_it(self):
        self._commit(key="idem-1", approval="apr-1")
        self.assertEqual(self.store.get_consumed_approval("apr-1"), "idem-1")

    def test_state_survives_a_new_store_on_the_same_file(self):
        """A container restart must not forget which effects already happened."""
        self._commit()
        reopened = EffectStore(pathlib.Path(self._tmp.name) / "effects.db")
        self.assertEqual(reopened.get("idem-1"), {"work_order_id": "WO-1"})
        with self.assertRaises(ValueError):
            reopened.commit_effect(
                idempotency_key="idem-other", incident_id="INC-1",
                tool_name="x", approval_id="apr-1", result={})

    def test_concurrent_commits_of_one_approval_yield_one_effect(self):
        import threading
        errors: list[Exception] = []

        def attempt(n: int) -> None:
            try:
                self._commit(key=f"idem-{n}", approval="apr-shared")
            except Exception as exc:          # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=attempt, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        committed = [n for n in range(6) if self.store.get(f"idem-{n}")]
        self.assertEqual(len(committed), 1, f"exactly one should win, got {committed}")
        self.assertEqual(len(errors), 5)
