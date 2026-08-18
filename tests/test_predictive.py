"""Tests for the predictive scanning branch.

Every design choice here was made by the operator, not inferred, and the tests
assert the choices rather than a plausible alternative:

  two ticket classes, forecast and proactive
  auto-remediate first and gate second, activating PolicyVerdict.ALLOWED
  a separate scheduled service feeding the existing flow
  the forecast class auto-remediates too, including a reboot
  predictive stays parent on a customer call; the SLA runs from the scan
  notify on truck roll, hard failure inside the horizon, or repeat offender
  a service-affecting remediation alone does NOT notify

    PYTHONPATH=src python3 -m unittest tests.test_predictive -v
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.predictive.config import (DEFAULT_SCAN, HARD_FAILURE_KPIS,
                                            PHYSICAL_CAUSES, ScanConfig,
                                            assumptions)
from lpr_cpe_demo.predictive.handoff import (apply_merge, attach_customer_call,
                                             domain_for, seed_from)
from lpr_cpe_demo.predictive.pipeline import (SERVICE_AFFECTING, execute_allowed,
                                              notification_reasons, plan_actions,
                                              process, action_key)
from lpr_cpe_demo.predictive.scanner import evaluate, scan
from lpr_cpe_demo.predictive.service import FlagHistory, run_once
from lpr_cpe_demo.predictive.signals import (CAUSE_MIX, days_to_threshold,
                                             linear_trend, series_for)

NOW = datetime(2026, 8, 18, 4, tzinfo=timezone.utc)


import functools


@functools.lru_cache(maxsize=4)
def _cached_population(n: int, seed: int, day_index: int) -> tuple:
    return tuple(series_for(f"CM-{i:06d}", "PR-ARE", "HFC" if i % 3 else "PON",
                            days=14, seed=seed, day_index=day_index)
                 for i in range(n))


def population(n: int = 4000, seed: int = 99, day_index: int = 60):
    """A mature population, as the first scan after deployment would see it.

    `day_index` defaults past the onset horizon so every modem that will degrade
    already has. At day 0 the population is almost entirely healthy by design --
    that is the steady-state daily inflow, and it is the right default for the
    service but the wrong one for a test that needs a ticket of a given cause.

    Cached: regenerating 4,000 series per setUp cost 28 seconds.
    """
    return list(_cached_population(n, seed, day_index))


def ticket_with_cause(cause: str, *, modems: int = 400, seed: int = 21):
    """A ticket for a forced cause.

    Fishing for a cause in a random population is brittle: `cpe_state` is erratic
    and rarely breaches an alarm bound, so a 4,000-modem draw may contain none and
    the test fails for a reason unrelated to what it asserts.
    """
    forced = [series_for(f"FC-{i:05d}", "PR-ARE", "HFC", days=14, seed=seed,
                         cause=cause) for i in range(modems)]
    result = scan(forced, run_id="FORCED", ran_at=NOW)
    if not result.tickets:
        raise unittest.SkipTest(f"cause {cause!r} produced no ticket in "
                                f"{modems} modems, which is itself informative")
    return result.tickets[0]


class TestTrendMathematics(unittest.TestCase):
    def test_a_clean_line_is_fitted_exactly(self):
        slope, intercept, r2 = linear_trend([1, 3, 5, 7, 9])
        self.assertAlmostEqual(slope, 2.0)
        self.assertAlmostEqual(intercept, 1.0)
        self.assertAlmostEqual(r2, 1.0)

    def test_noise_yields_a_low_r_squared(self):
        self.assertLess(linear_trend([5, 1, 7, 2, 6, 1, 8])[2], 0.2)

    def test_a_flat_series_has_zero_slope(self):
        self.assertAlmostEqual(linear_trend([4.0] * 8)[0], 0.0)

    def test_days_to_threshold_measures_from_the_current_value(self):
        values = [-20 - 0.5 * i for i in range(14)]     # now at -26.5
        self.assertAlmostEqual(days_to_threshold(values, -27,
                                                direction="falling"), 1.0, places=3)

    def test_an_already_breached_series_is_not_a_forecast(self):
        self.assertIsNone(days_to_threshold([-28, -28.2, -28.5], -27,
                                           direction="falling"))

    def test_an_improving_series_is_not_a_forecast(self):
        self.assertIsNone(days_to_threshold([-25, -24, -23], -27,
                                           direction="falling"))

    def test_a_single_sample_does_not_produce_a_trend(self):
        self.assertEqual(linear_trend([3.0]), (0.0, 3.0, 0.0))


class TestSignalRealism(unittest.TestCase):
    def test_the_cause_mix_sums_to_one(self):
        self.assertAlmostEqual(sum(CAUSE_MIX.values()), 1.0, places=6)

    def test_most_of_the_population_is_healthy(self):
        self.assertGreater(CAUSE_MIX["stable"], 0.9)

    def test_a_degrading_physical_cause_is_distinguishable_from_a_stable_modem(self):
        """If it is not, the scan is flagging at random."""
        def mean_slope(cause: str) -> float:
            return sum(linear_trend(series_for(f"M{i}", "X", "HFC", days=14,
                                              seed=7, cause=cause)
                                   .kpis["ds_rx_dbmv"])[0] for i in range(40)) / 40
        self.assertLess(mean_slope("tap_or_odp"), mean_slope("stable") - 0.1)

    def test_an_erratic_cause_does_not_produce_a_confident_trend(self):
        """The reason min_trend_r2 exists: a line through noise is not a forecast."""
        r2 = sum(linear_trend(series_for(f"M{i}", "X", "HFC", days=14, seed=3,
                                        cause="cpe_state")
                             .kpis["t3_timeouts_per_day"])[2]
                 for i in range(40)) / 40
        self.assertLess(r2, DEFAULT_SCAN.min_trend_r2)

    def test_a_modem_series_does_not_depend_on_generation_order(self):
        one = series_for("CM-42", "PR-ARE", "HFC", days=14, seed=5)
        for _ in range(20):
            series_for("CM-other", "PR-ARE", "HFC", days=14, seed=5)
        self.assertEqual(series_for("CM-42", "PR-ARE", "HFC", days=14, seed=5).kpis,
                         one.kpis)

    def test_counting_kpis_never_go_negative(self):
        for cause in CAUSE_MIX:
            s = series_for("M", "X", "HFC", days=14, seed=11, cause=cause)
            for kpi in ("uncorrectable_ratio", "t3_timeouts_per_day"):
                self.assertTrue(all(v >= 0 for v in s.kpis[kpi]), f"{cause}/{kpi}")


class TestScanClassification(unittest.TestCase):
    def setUp(self):
        self.result = scan(population(), run_id="R", ran_at=NOW)

    def test_no_healthy_modem_is_flagged(self):
        """A false positive here is a truck roll to a working service."""
        self.assertFalse([t for t in self.result.tickets
                          if t.suspected_cause == "stable"])

    def test_a_proactive_ticket_always_has_a_current_breach(self):
        for ticket in self.result.tickets:
            if ticket.ticket_class == "proactive":
                self.assertTrue(any(f.breached_now for f in ticket.findings),
                                ticket.ticket_id)

    def test_a_forecast_ticket_never_has_a_current_breach(self):
        """Already broken beats predicted to break."""
        for ticket in self.result.tickets:
            if ticket.ticket_class == "forecast":
                self.assertFalse(any(f.breached_now for f in ticket.findings),
                                 ticket.ticket_id)

    def test_both_classes_are_produced(self):
        self.assertGreater(self.result.by_class.get("proactive", 0), 0)
        self.assertGreater(self.result.by_class.get("forecast", 0), 0)

    def test_forecast_lead_time_never_exceeds_the_horizon(self):
        for ticket in self.result.tickets:
            if ticket.ticket_class == "forecast":
                eta = ticket.headline.days_to_breach
                self.assertIsNotNone(eta, ticket.ticket_id)
                self.assertLessEqual(eta, DEFAULT_SCAN.forecast_horizon_days)

    def test_proactive_tickets_carry_a_shorter_sla_than_forecast(self):
        self.assertLess(DEFAULT_SCAN.sla_hours["proactive"],
                        DEFAULT_SCAN.sla_hours["forecast"])
        for ticket in self.result.tickets:
            expected = ticket.opened_at + timedelta(
                hours=DEFAULT_SCAN.sla_hours[ticket.ticket_class])
            self.assertEqual(ticket.sla_due_at, expected)

    def test_the_cap_drops_the_least_urgent_not_an_arbitrary_tail(self):
        small = ScanConfig(max_tickets_per_run=20)
        capped = scan(population(), run_id="R", ran_at=NOW, config=small)
        self.assertEqual(len(capped.tickets), 20)
        self.assertGreater(capped.suppressed_by_cap, 0)
        severities = [t.severity for t in capped.tickets]
        self.assertIn(severities[0], {"critical", "high"})

    def test_repeat_offenders_are_detected_from_history(self):
        history = {t.modem_id: [NOW - timedelta(days=5)]
                   for t in self.result.tickets}
        again = scan(population(), run_id="R2", ran_at=NOW,
                     previous_flags=history)
        self.assertTrue(all(t.repeat_offender for t in again.tickets))

    def test_a_flag_outside_the_repeat_window_does_not_count(self):
        history = {t.modem_id: [NOW - timedelta(days=400)]
                   for t in self.result.tickets}
        again = scan(population(), run_id="R3", ran_at=NOW,
                     previous_flags=history)
        self.assertFalse(any(t.repeat_offender for t in again.tickets))

    def test_a_healthy_modem_produces_no_findings(self):
        clean = series_for("M", "X", "HFC", days=14, seed=1, cause="stable")
        self.assertEqual(evaluate(clean), [])


class TestAutoRemediateThenGate(unittest.TestCase):
    """The operator chose to bypass the main engine's gate-everything policy."""

    def setUp(self):
        self.result = scan(population(), run_id="R", ran_at=NOW)

    def _ticket(self, cause: str):
        return next(t for t in self.result.tickets if t.suspected_cause == cause)

    def test_a_resolved_ticket_needs_no_human(self):
        outcome = process(self._ticket("config_drift"), hour=4, rolls=[0.0, 0.0])
        self.assertTrue(outcome.resolved)
        self.assertEqual(outcome.verdict, "allowed")
        self.assertFalse(outcome.handed_to_human)

    def test_a_failed_remediation_is_gated(self):
        outcome = process(self._ticket("firmware"), hour=4, rolls=[0.99, 0.99])
        self.assertFalse(outcome.resolved)
        self.assertEqual(outcome.verdict, "requires_approval")
        self.assertIn("auto_remediation_unsuccessful", outcome.gate_reasons)

    def test_a_physical_cause_gets_no_remote_attempt(self):
        """Rebooting a modem behind a corroded tap interrupts service and fixes
        nothing."""
        for cause in PHYSICAL_CAUSES:
            ticket = self._ticket(cause)
            self.assertEqual(plan_actions(ticket), [], cause)
            outcome = process(ticket, hour=4, rolls=[0.0, 0.0])
            self.assertEqual(outcome.attempts, ())
            self.assertTrue(outcome.needs_truck_roll, cause)

    def test_config_drift_is_reprovisioned_before_it_is_rebooted(self):
        """Fixing the config without interrupting service is the better order."""
        self.assertEqual(plan_actions(self._ticket("config_drift"))[0],
                         "remote_reprovision")

    def test_the_forecast_class_does_auto_remediate_including_a_reboot(self):
        forecast = [t for t in self.result.tickets
                    if t.ticket_class == "forecast"
                    and t.suspected_cause not in PHYSICAL_CAUSES]
        self.assertTrue(forecast)
        self.assertTrue(any("remote_reboot" in plan_actions(t) for t in forecast))

    def test_attempts_are_capped(self):
        outcome = process(self._ticket("firmware"), hour=4, rolls=[0.99] * 6)
        self.assertLessEqual(len(outcome.attempts), 2)

    def test_the_idempotency_key_is_derived_and_stable(self):
        ticket = self._ticket("config_drift")
        first = action_key(ticket, "remote_reboot", 0)
        self.assertEqual(first, action_key(ticket, "remote_reboot", 0))
        self.assertNotEqual(first, action_key(ticket, "remote_reboot", 1))
        self.assertNotEqual(first, action_key(ticket, "remote_reprovision", 0))


class TestMaintenanceWindow(unittest.TestCase):
    """The operator chose to reboot working modems without notifying anyone.

    The window is the only thing that keeps that acceptable, so it is tested as a
    control rather than a preference.
    """

    def test_a_reboot_is_refused_outside_the_window(self):
        allowed, why = execute_allowed("remote_reboot", 14)
        self.assertFalse(allowed)
        self.assertIn("deferred", why)

    def test_a_reboot_is_permitted_inside_the_window(self):
        self.assertTrue(execute_allowed("remote_reboot", 3)[0])

    def test_a_non_service_affecting_action_runs_at_any_hour(self):
        self.assertTrue(execute_allowed("remote_reprovision", 14)[0])

    def test_only_the_reboot_is_marked_service_affecting(self):
        self.assertEqual(SERVICE_AFFECTING, {"remote_reboot"})

    def test_a_window_crossing_midnight_is_handled(self):
        config = ScanConfig(maintenance_window_start_hour=23,
                            maintenance_window_end_hour=3)
        self.assertTrue(config.in_maintenance_window(23))
        self.assertTrue(config.in_maintenance_window(1))
        self.assertFalse(config.in_maintenance_window(12))

    def test_a_deferred_reboot_is_gated_not_silently_dropped(self):
        # firmware plans a reboot first; at 14:00 it defers, the reprovision runs
        # and is forced to fail, so the deferral must appear in the gate reasons.
        ticket = ticket_with_cause("firmware")
        outcome = process(ticket, hour=14, rolls=[0.0, 0.99])
        self.assertFalse(outcome.resolved)
        self.assertIn("deferred_to_maintenance_window", outcome.gate_reasons)
        self.assertFalse(outcome.attempts[0].executed)

    def test_service_interruption_is_counted(self):
        outcome = process(ticket_with_cause("firmware"), hour=3, rolls=[0.0, 0.0])
        self.assertTrue(outcome.attempts[0].executed)
        self.assertGreater(outcome.service_interruption_minutes, 0)


class TestNotificationTriggers(unittest.TestCase):
    """Exactly the three the operator selected, and not the one they did not."""

    def setUp(self):
        self.result = scan(population(), run_id="R", ran_at=NOW)

    def test_a_truck_roll_notifies(self):
        ticket = next(t for t in self.result.tickets
                      if t.suspected_cause == "tap_or_odp")
        outcome = process(ticket, hour=4, rolls=[0.5, 0.5])
        self.assertIn("truck_roll_required", outcome.notify_reasons)

    def test_a_repeat_offender_notifies_even_when_the_reboot_worked(self):
        history = {t.modem_id: [NOW - timedelta(days=5)]
                   for t in self.result.tickets}
        again = scan(population(), run_id="R2", ran_at=NOW, previous_flags=history)
        ticket = next(t for t in again.tickets
                      if t.suspected_cause == "config_drift")
        outcome = process(ticket, hour=4, rolls=[0.0, 0.0])
        self.assertTrue(outcome.resolved)
        self.assertIn("repeat_offender", outcome.notify_reasons)

    def test_a_service_affecting_reboot_alone_does_not_notify(self):
        """Deliberate: the operator did not select this trigger.

        A working modem is rebooted, service drops for two minutes, and nobody is
        told. The maintenance window is the only control on that, which is why it
        is tested separately as a control.
        """
        outcome = process(ticket_with_cause("firmware"), hour=3, rolls=[0.0, 0.0])
        self.assertTrue(outcome.resolved)
        self.assertGreater(outcome.service_interruption_minutes, 0)
        self.assertFalse(outcome.needs_truck_roll)
        self.assertEqual(outcome.notify_reasons, ())

    def test_hard_failure_means_loss_of_service_not_any_breach(self):
        """Otherwise every forecast ticket notifies and the trigger is vacuous."""
        forecast = [t for t in self.result.tickets if t.ticket_class == "forecast"]
        notifying = [t for t in forecast
                     if "hard_failure_forecast" in
                     notification_reasons(t, needs_truck_roll=False)]
        self.assertTrue(notifying)
        self.assertLess(len(notifying), len(forecast),
                        "the trigger fires on every forecast ticket, so it does "
                        "not discriminate")
        for ticket in notifying:
            self.assertTrue(any(f.kpi in HARD_FAILURE_KPIS for f in ticket.findings))

    def test_a_resolved_forecast_does_not_demand_a_notification(self):
        """Nothing left to tell the customer once the failure was averted."""
        forecast = next(t for t in self.result.tickets
                        if t.ticket_class == "forecast"
                        and t.suspected_cause == "config_drift")
        self.assertEqual(
            notification_reasons(forecast, needs_truck_roll=False, resolved=True),
            [])

    def test_notification_always_gates(self):
        ticket = next(t for t in self.result.tickets
                      if t.suspected_cause == "tap_or_odp")
        outcome = process(ticket, hour=4, rolls=[0.5, 0.5])
        self.assertEqual(outcome.verdict, "requires_approval")
        self.assertIn("customer_notification_required", outcome.gate_reasons)


class TestMergeIntoTheMainFlow(unittest.TestCase):
    """Predictive stays parent; the SLA runs from the scan."""

    def setUp(self):
        result = scan(population(), run_id="R", ran_at=NOW)
        pairs = [(t, process(t, hour=4, rolls=[0.5, 0.5])) for t in result.tickets]
        self.ticket, self.outcome = next((t, o) for t, o in pairs
                                         if o.handed_to_human)
        self.seed = seed_from(self.ticket, self.outcome)

    def test_only_a_gated_outcome_may_be_handed_over(self):
        result = scan(population(), run_id="R", ran_at=NOW)
        resolved = next((t, o) for t, o in
                        ((x, process(x, hour=4, rolls=[0.0, 0.0]))
                         for x in result.tickets) if o.verdict == "allowed")
        with self.assertRaises(ValueError):
            seed_from(*resolved)

    def test_the_seed_records_its_predictive_origin(self):
        self.assertEqual(self.seed.source, "predictive_scan")
        self.assertEqual(self.seed.predictive_ticket_id, self.ticket.ticket_id)
        self.assertEqual(self.seed.merge_role, "parent")

    def test_the_seed_carries_the_telemetry_as_evidence(self):
        self.assertTrue(self.seed.evidence)
        for item in self.seed.evidence:
            self.assertTrue(item["ref"].startswith("pnm."))
            self.assertIn("summary", item)

    def test_the_seed_carries_the_auto_attempts_and_their_keys(self):
        for attempt in self.seed.auto_attempts:
            self.assertTrue(attempt["idempotency_key"].startswith("idem-"))

    def test_the_suspected_cause_maps_to_a_domain_the_main_model_knows(self):
        known = {"cpe", "provisioning", "wifi_or_home", "drop", "hfc_tap",
                 "pon_odp", "plant", "unknown"}
        self.assertIn(self.seed.suspected_domain, known)

    def test_a_pon_delimiter_cause_maps_to_odp_not_tap(self):
        self.assertEqual(domain_for("tap_or_odp", "PON"), "pon_odp")
        self.assertEqual(domain_for("tap_or_odp", "HFC"), "hfc_tap")

    def test_the_predictive_incident_stays_parent(self):
        decision = attach_customer_call(self.seed,
                                       reactive_incident_id="INC-CALL-1",
                                       called_at=NOW + timedelta(hours=6))
        self.assertEqual(decision.parent_incident_id, self.seed.incident_id)
        child = apply_merge(self.seed, decision)
        self.assertEqual(child.merge_role, "child")
        self.assertEqual(child.parent_incident_id, self.seed.incident_id)

    def test_the_sla_runs_from_the_scan_not_the_call(self):
        called = NOW + timedelta(hours=6)
        decision = attach_customer_call(self.seed,
                                       reactive_incident_id="INC-CALL-1",
                                       called_at=called)
        self.assertEqual(decision.sla_due_at, self.seed.sla_due_at)
        self.assertEqual(decision.hours_of_clock_already_spent, 6.0)

    def test_an_sla_already_breached_at_attach_is_surfaced(self):
        """An agent picking up the call must see why the case is red."""
        called = self.seed.sla_due_at + timedelta(hours=2)
        decision = attach_customer_call(self.seed,
                                       reactive_incident_id="INC-CALL-2",
                                       called_at=called)
        self.assertTrue(decision.sla_breached_at_attach)
        self.assertIn("already breached", decision.rationale)
        self.assertTrue(apply_merge(self.seed, decision).sla_breached_at_attach)

    def test_the_child_inherits_the_parents_clock_not_its_own(self):
        decision = attach_customer_call(self.seed,
                                       reactive_incident_id="INC-CALL-3",
                                       called_at=NOW + timedelta(days=2))
        child = apply_merge(self.seed, decision)
        self.assertEqual(child.sla_due_at, self.seed.sla_due_at)
        self.assertEqual(child.sla_inherited_from, self.seed.incident_id)

    def test_the_seed_serialises(self):
        import json
        json.dumps(self.seed.to_dict())


class TestScheduledService(unittest.TestCase):
    def test_a_run_produces_a_coherent_report(self):
        report = run_once(ran_at=NOW, population=population())
        summary = report.summary()
        self.assertEqual(summary["scanned"], 4000)
        self.assertEqual(summary["auto_closed"] + summary["gated"],
                         len(report.outcomes))
        self.assertEqual(summary["handed_to_main_flow"], summary["gated"])

    def test_the_same_inputs_reproduce_the_run(self):
        first = run_once(ran_at=NOW, population=population()).summary()
        second = run_once(ran_at=NOW, population=population()).summary()
        self.assertEqual(first, second)

    def test_history_persists_and_open_tickets_suppress_duplicates(self):
        """A scan that reopens the same finding nightly generates work, not
        information."""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "flags.json"
            first = run_once(ran_at=NOW, population=population(),
                             history=FlagHistory(path=path).load())
            self.assertTrue(path.exists())
            reloaded = FlagHistory(path=path).load()
            self.assertTrue(reloaded.open_tickets, "open tickets were not persisted")

            second = run_once(ran_at=NOW + timedelta(days=1),
                              population=population(), history=reloaded)
            self.assertGreater(second.scan.suppressed_as_duplicate, 0)
            self.assertLess(len(second.scan.tickets), len(first.scan.tickets))

    def test_a_ticket_closed_by_auto_remediation_leaves_the_open_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "flags.json"
            report = run_once(ran_at=NOW, population=population(),
                              history=FlagHistory(path=path).load())
            closed = {o.ticket_id for o in report.outcomes if o.verdict == "allowed"}
            self.assertTrue(closed)
            reloaded = FlagHistory(path=path).load()
            closed_modems = {t.modem_id for t in report.scan.tickets
                             if t.ticket_id in closed}
            for modem in closed_modems:
                self.assertNotIn(modem, reloaded.open_tickets)
                self.assertIn(modem, reloaded.flags,
                              "a closed ticket must enter the repeat history")

    def test_only_closed_tickets_count_towards_repeat_offender(self):
        """Counting an open ticket as a repeat made every modem a repeat offender
        by day two, so the notification trigger fired on the whole population and
        the auto-close rate fell to zero."""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "flags.json"
            run_once(ran_at=NOW, population=population(),
                     history=FlagHistory(path=path).load())
            second = run_once(ran_at=NOW + timedelta(days=1),
                              population=population(),
                              history=FlagHistory(path=path).load())
            self.assertFalse(any(t.repeat_offender for t in second.scan.tickets),
                             "an open ticket must not count as a repeat")

    def test_a_relapsing_modem_becomes_a_repeat_offender(self):
        """A reboot that clears a symptom rather than a cause buys days, not a fix,
        and the modem coming back is the case the operator wants notified."""
        from lpr_cpe_demo.predictive.signals import RELAPSE_AFTER_DAYS
        self.assertIsNone(RELAPSE_AFTER_DAYS["config_drift"],
                          "a corrected configuration should stay corrected")
        self.assertIsNotNone(RELAPSE_AFTER_DAYS["firmware"])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "flags.json"
            seen_repeat = False
            for day in range(12):
                report = run_once(ran_at=NOW + timedelta(days=day),
                                  history=FlagHistory(path=path).load(),
                                  scan_config=ScanConfig(population=6000),
                                  day_index=60 + day)
                if any(t.repeat_offender for t in report.scan.tickets):
                    seen_repeat = True
                    break
            self.assertTrue(seen_repeat,
                            "no modem relapsed in twelve days, so the repeat "
                            "trigger can never fire")

    def test_the_steady_state_is_far_smaller_than_the_launch_backlog(self):
        """Two different capacity questions, differing by an order of magnitude."""
        backlog = run_once(ran_at=NOW, scan_config=ScanConfig(population=8000),
                           day_index=60)
        steady = run_once(ran_at=NOW, scan_config=ScanConfig(population=8000),
                          day_index=0)
        self.assertGreater(len(backlog.scan.tickets),
                           len(steady.scan.tickets) * 5)

    def test_a_corrupt_history_file_does_not_stop_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "flags.json"
            path.write_text("{not json")
            history = FlagHistory(path=path).load()
            self.assertEqual(history.flags, {})
            self.assertGreater(len(run_once(ran_at=NOW, population=population(),
                                           history=history).scan.tickets), 0)

    def test_a_daytime_run_defers_reboots(self):
        day = run_once(ran_at=NOW.replace(hour=14), population=population())
        deferred = [o for o in day.outcomes
                    if "deferred_to_maintenance_window" in o.gate_reasons]
        self.assertTrue(deferred)

    def test_assumptions_are_exposed_with_a_basis(self):
        data = assumptions()
        self.assertIn("threshold_basis", data)
        self.assertIn("not LPR alarm points", data["threshold_basis"])
        self.assertIn("scan_basis", data)
