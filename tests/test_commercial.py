"""Tests for commercial dispatch prioritisation.

Three of these assert findings that emerged from measurement rather than design,
and each one changed the model:

  a positive-gap threshold would decline 87% of repairs
  protections alone exceed a day's capacity
  cost is geography, so the ranking skews against islands and mountains

    PYTHONPATH=src python3 -m unittest tests.test_commercial -v
"""
from __future__ import annotations

import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.commercial import (BLAST_RADIUS_PLANT_EVENT,  # noqa: E402
                                     CONTRACT_MOBILITY, PAYMENT_COLLECTABILITY,
                                     PROTECTION_REASON, CustomerRecord,
                                     allocate_capacity, assumptions,
                                     churn_probability, disparate_impact,
                                     protections_for, rank,
                                     threshold_would_decline, truck_roll_cost,
                                     value_at_risk)
from lpr_cpe_demo.geography import sites_in_cpe_footprint  # noqa: E402
from lpr_cpe_demo.plant import households  # noqa: E402


def customer(**kw) -> CustomerRecord:
    base = dict(account_id="A-1", segment="residential",
                monthly_recurring_revenue=70.0, tenure_months=24,
                contract_status="rolling", contract_months_remaining=0,
                payment_status="current")
    base.update(kw)
    return CustomerRecord(**base)


def population(n: int = 600, seed: int = 20260818):
    rng = random.Random(seed)
    sites = list(sites_in_cpe_footprint())
    weights = [households(s) for s in sites]
    out = []
    for i in range(n):
        site = rng.choices(sites, weights=weights, k=1)[0]
        segment = rng.choices(["residential", "smb", "enterprise"], [86, 11, 3])[0]
        mrr = {"residential": rng.uniform(35, 110), "smb": rng.uniform(120, 380),
               "enterprise": rng.uniform(350, 1400)}[segment]
        status = rng.choice(["in_term", "in_term", "rolling", "expiring_soon",
                             "out_of_term"])
        out.append((f"T{i:05d}", customer(
            account_id=f"A{i:05d}", segment=segment,
            monthly_recurring_revenue=round(mrr, 2),
            tenure_months=rng.randint(2, 96), contract_status=status,
            contract_months_remaining=rng.randint(1, 23) if status == "in_term" else 0,
            payment_status=rng.choices(
                ["current", "late", "arrears_30", "arrears_60", "arrears_90_plus"],
                [75, 10, 7, 5, 3])[0],
            faults_in_last_90d=rng.choices([0, 1, 2, 3], [70, 20, 7, 3])[0],
            medical_or_safety_flag=rng.random() < 0.008,
            vulnerable_flag=rng.random() < 0.02,
            lifeline_subsidised=rng.random() < 0.06), site.site_id,
            {"households_affected": rng.choices([1, 4, 6, 8], [85, 7, 5, 3])[0],
             "sla_breached": rng.random() < 0.04,
             "service_down": rng.random() < 0.09}))
    return out


class TestValueIsRiskNotSize(unittest.TestCase):
    """Value at risk is LTV times the probability a dispatch buys back, so a large
    customer who cannot leave is not the priority a weighted sum would make them."""

    def test_a_locked_in_customer_has_less_at_risk_than_an_out_of_term_one(self):
        locked = value_at_risk(customer(segment="enterprise",
                                        monthly_recurring_revenue=480.0,
                                        contract_status="in_term",
                                        contract_months_remaining=19))
        loose = value_at_risk(customer(segment="enterprise",
                                       monthly_recurring_revenue=480.0,
                                       contract_status="out_of_term"))
        self.assertLess(locked.value_at_risk, loose.value_at_risk)

    def test_contract_status_enters_through_the_probability_not_as_a_weight(self):
        self.assertLess(CONTRACT_MOBILITY["in_term"],
                        CONTRACT_MOBILITY["out_of_term"])
        self.assertLess(CONTRACT_MOBILITY["in_term"],
                        CONTRACT_MOBILITY["pending_disconnect"])

    def test_arrears_raise_churn_and_lower_collectability_separately(self):
        """Two effects, deliberately not merged: likelier to leave, worth less if
        they stay."""
        current = customer(payment_status="current")
        arrears = customer(payment_status="arrears_90_plus")
        self.assertGreater(churn_probability(arrears), churn_probability(current))
        self.assertLess(PAYMENT_COLLECTABILITY["arrears_90_plus"],
                        PAYMENT_COLLECTABILITY["current"])
        self.assertLess(value_at_risk(arrears).collectable_value,
                        value_at_risk(current).collectable_value)

    def test_repeat_faults_dominate_the_churn_uplift(self):
        once = churn_probability(customer(faults_in_last_90d=1))
        thrice = churn_probability(customer(faults_in_last_90d=3))
        self.assertGreater(thrice, once * 2)

    def test_churn_probability_is_bounded(self):
        worst = customer(segment="residential", contract_status="pending_disconnect",
                         payment_status="suspended", faults_in_last_90d=9)
        self.assertLessEqual(churn_probability(worst), 0.95)

    def test_an_in_term_customer_is_valued_over_the_remaining_term(self):
        record = customer(contract_status="in_term", contract_months_remaining=19)
        self.assertEqual(record.expected_remaining_months, 19)

    def test_value_is_never_negative(self):
        for status in PAYMENT_COLLECTABILITY:
            self.assertGreaterEqual(
                value_at_risk(customer(payment_status=status)).value_at_risk, 0.0)


class TestCostIsPerCustomerNotAnAverage(unittest.TestCase):
    def test_an_island_visit_costs_more_than_a_metro_one(self):
        self.assertGreater(truck_roll_cost("PR-CUL"), truck_roll_cost("PR-BAY") * 2)

    def test_a_mountain_visit_costs_more_than_a_metro_one(self):
        self.assertGreater(truck_roll_cost("PR-UTU"), truck_roll_cost("PR-BAY"))

    def test_the_ferry_and_overnight_premiums_both_apply(self):
        self.assertGreater(truck_roll_cost("PR-VQS"), 500)


class TestProtectionsOverrideValue(unittest.TestCase):
    def test_a_medical_flag_protects(self):
        self.assertIn("medical_or_safety",
                      protections_for(customer=customer(medical_or_safety_flag=True)))

    def test_a_lifeline_subsidy_carries_a_regulatory_obligation(self):
        self.assertIn("regulatory_obligation",
                      protections_for(customer=customer(lifeline_subsidised=True)))

    def test_a_breached_sla_protects_regardless_of_value(self):
        self.assertIn("sla_breached", protections_for(sla_breached=True))

    def test_total_loss_of_service_protects(self):
        self.assertIn("total_loss_of_service", protections_for(service_down=True))

    def test_blast_radius_is_not_a_protection(self):
        """It is expressed once, as a value multiplier. Counting it twice filled
        every slot in a day and the commercial ranking never ran."""
        self.assertNotIn("multi_household_blast_radius", PROTECTION_REASON)
        self.assertEqual(protections_for(households_affected=99), ())

    def test_blast_radius_still_raises_value(self):
        single = rank([("T1", customer(), "PR-BAY", {"households_affected": 1})])[0]
        shared = rank([("T2", customer(), "PR-BAY", {"households_affected": 8})])[0]
        self.assertGreater(shared.value.value_at_risk, single.value.value_at_risk)

    def test_protected_candidates_rank_ahead_of_every_commercial_one(self):
        rich = customer(account_id="RICH", segment="enterprise",
                        monthly_recurring_revenue=1400.0,
                        contract_status="out_of_term")
        poor = customer(account_id="POOR", monthly_recurring_revenue=35.0,
                        medical_or_safety_flag=True)
        ranked = rank([("T-rich", rich, "PR-BAY", {}),
                       ("T-poor", poor, "PR-BAY", {})])
        self.assertEqual(ranked[0].account_id, "POOR")

    def test_value_still_orders_within_the_protected_band(self):
        """A protection guarantees attention without discarding the economics."""
        big = customer(account_id="BIG", segment="enterprise",
                       monthly_recurring_revenue=1400.0,
                       contract_status="out_of_term", medical_or_safety_flag=True)
        small = customer(account_id="SMALL", monthly_recurring_revenue=35.0,
                         medical_or_safety_flag=True)
        ranked = rank([("T-small", small, "PR-BAY", {}),
                       ("T-big", big, "PR-BAY", {})])
        self.assertEqual([r.account_id for r in ranked], ["BIG", "SMALL"])


class TestTheGapIsAnOrderingNotAThreshold(unittest.TestCase):
    """MEASURED: 87% of commercially ranked candidates have a negative gap."""

    def setUp(self):
        self.ranked = rank(population())

    def test_most_candidates_have_a_negative_gap(self):
        report = threshold_would_decline(self.ranked)
        self.assertGreater(report["declined_share"], 0.5,
                           "if this ever falls below half, the note in "
                           "allocate_capacity needs rewriting")

    def test_the_report_quantifies_what_a_threshold_would_abandon(self):
        report = threshold_would_decline(self.ranked)
        self.assertGreater(report["value_at_risk_abandoned"], 0)
        self.assertIn("does not decide whether a fault deserves a visit",
                      report["verdict"])

    def test_capacity_allocation_schedules_down_the_ranking(self):
        plan = allocate_capacity(self.ranked, slots=40)
        self.assertEqual(len(plan.scheduled), 40)
        self.assertEqual(len(plan.deferred), len(self.ranked) - 40)

    def test_deferred_is_not_declined(self):
        """Nothing is abandoned; it waits for tomorrow's capacity."""
        plan = allocate_capacity(self.ranked, slots=40)
        self.assertGreater(plan.deferred_value_at_risk, 0)

    def test_zero_slots_is_valid_and_schedules_nothing(self):
        plan = allocate_capacity(self.ranked, slots=0)
        self.assertEqual(plan.scheduled, ())

    def test_negative_slots_is_rejected(self):
        with self.assertRaises(ValueError):
            allocate_capacity(self.ranked, slots=-1)

    def test_more_slots_than_candidates_is_safe(self):
        plan = allocate_capacity(self.ranked, slots=99_999)
        self.assertEqual(len(plan.scheduled), len(self.ranked))
        self.assertEqual(plan.deferred, ())


class TestProtectionsExceedADaysCapacity(unittest.TestCase):
    """MEASURED: 23% of candidates are protected, so a 40-slot day never reaches an
    unprotected ticket. The number worth taking to a capacity conversation."""

    def setUp(self):
        self.ranked = rank(population())

    def test_the_break_even_capacity_is_reported(self):
        plan = allocate_capacity(self.ranked, slots=40)
        self.assertGreater(plan.slots_before_commercial_ranking_bites, 40)

    def test_a_small_day_is_filled_entirely_by_protections(self):
        plan = allocate_capacity(self.ranked, slots=40)
        self.assertFalse(plan.commercial_ranking_active)
        self.assertEqual(plan.commercial_scheduled, 0)

    def test_a_large_enough_day_reaches_the_commercial_queue(self):
        protected = sum(1 for r in self.ranked if r.protections)
        plan = allocate_capacity(self.ranked, slots=protected + 25)
        self.assertTrue(plan.commercial_ranking_active)
        self.assertEqual(plan.commercial_scheduled, 25)


class TestDisparateImpactIsMeasured(unittest.TestCase):
    """Cost is dominated by geography, so a net-benefit queue deprioritises the
    hardest-to-reach customers structurally. Computed, not left to a complaint."""

    def setUp(self):
        self.impact = disparate_impact(rank(population()))

    def test_the_skew_is_reported_per_archetype(self):
        self.assertEqual(set(self.impact["bottom_minus_top"]),
                         set(self.impact["overall_share"]))

    def test_metro_is_favoured_over_the_harder_archetypes(self):
        skew = self.impact["bottom_minus_top"]
        self.assertLess(skew["metro"], 0.0,
                        "metro should be over-represented in the top quartile")

    def test_at_least_one_archetype_is_measurably_deprioritised(self):
        self.assertGreater(self.impact["most_deprioritised_skew"], 0.0)

    def test_islands_never_reach_the_top_quartile(self):
        self.assertEqual(self.impact["top_quartile_share"].get("remote_island", 0.0),
                         0.0)

    def test_the_report_carries_the_warning(self):
        self.assertIn("commercial", self.impact["warning"])

    def test_an_all_protected_population_reports_no_ordering(self):
        protected = [("T1", customer(medical_or_safety_flag=True), "PR-BAY", {})]
        self.assertEqual(disparate_impact(rank(protected))["commercial"], 0)


class TestWiredIntoTheFlow(unittest.TestCase):
    def test_a_dispatch_ticket_carries_a_priority(self):
        from datetime import datetime, timezone
        from lpr_cpe_demo.predictive.pipeline import process
        from lpr_cpe_demo.predictive.scanner import scan
        from lpr_cpe_demo.predictive.signals import series_for
        pop = [series_for(f"C{i}", "PR-VQS", "PON", days=14, seed=99, day_index=60,
                          cause="tap_or_odp") for i in range(120)]
        ticket = scan(pop, run_id="R",
                      ran_at=datetime(2026, 8, 18, 4, tzinfo=timezone.utc)).tickets[0]
        outcome = process(ticket, hour=4, rolls=[0.5, 0.5],
                          customer=customer(segment="enterprise",
                                            monthly_recurring_revenue=900.0,
                                            contract_status="out_of_term"))
        self.assertIsNotNone(outcome.priority)
        self.assertGreater(outcome.priority.cost_usd, 0)

    def test_a_remotely_resolved_ticket_carries_no_priority(self):
        """Ranking a ticket no crew will visit puts customer value into a decision
        that never involves one."""
        from datetime import datetime, timezone
        from lpr_cpe_demo.predictive.pipeline import process
        from lpr_cpe_demo.predictive.scanner import scan
        from lpr_cpe_demo.predictive.signals import series_for
        pop = [series_for(f"S{i}", "PR-BAY", "HFC", days=14, seed=7, day_index=60,
                          cause="config_drift") for i in range(120)]
        ticket = scan(pop, run_id="S",
                      ran_at=datetime(2026, 8, 18, 4, tzinfo=timezone.utc)).tickets[0]
        outcome = process(ticket, hour=4, rolls=[0.0, 0.0], customer=customer())
        self.assertTrue(outcome.resolved)
        self.assertIsNone(outcome.priority)

    def test_the_crm_feed_is_declared_in_the_data_contract(self):
        from lpr_cpe_demo.telemetry import DATA_CONTRACT
        panel = next(p for p in DATA_CONTRACT if p.panel == "commercial_priority")
        sources = " ".join(r.source_system for r in panel.requirements)
        self.assertIn("CRM", sources)

    def test_the_protection_flags_are_flagged_as_missing_not_assumed(self):
        """Their absence silently removes a safeguard, so it must not read as
        modelled."""
        from lpr_cpe_demo.telemetry import DATA_CONTRACT
        panel = next(p for p in DATA_CONTRACT if p.panel == "commercial_priority")
        flags = next(r for r in panel.requirements if "vulnerability" in r.field)
        self.assertEqual(flags.availability, "missing")
        self.assertIn("PROTECTION", flags.note)

    def test_the_dashboard_states_all_three_measured_constraints(self):
        from lpr_cpe_demo.dashboard import build
        block = build(count=20).block("commercial_priority")
        text = " ".join(row["finding"] + row["detail"] for row in block.data)
        self.assertIn("87%", text)
        self.assertIn("capacity", text)
        self.assertIn("geography", text)

    def test_the_assumptions_are_exposed_with_a_basis(self):
        data = assumptions()
        self.assertIn("ASSUMED", data["basis"])
        self.assertIn("churn_base_by_segment", data)
        self.assertEqual(data["blast_radius_plant_event"], BLAST_RADIUS_PLANT_EVENT)
