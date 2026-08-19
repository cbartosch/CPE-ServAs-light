"""Tests for the northbound contracts and adapters.

Three of the four systems are grounded in published specifications and one is not.
The tests assert that distinction as strongly as they assert the parsing, because
an integrator who mistakes the modelled NXT envelope for a real one will build
against field names nobody outside this repository has ever used.

    PYTHONPATH=src python3 -m unittest tests.test_northbound -v
"""
from __future__ import annotations

import copy
import pathlib
import sys
import unittest
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lpr_cpe_demo.northbound.adapters import (AdapterError, CpeSample,  # noqa: E402
                                              counter_rate, parse,
                                              parse_cpe_usp, parse_jtrack_ticket,
                                              parse_nxt_snapshot,
                                              parse_wfm_work_order)
from lpr_cpe_demo.northbound.contracts import (CONTRACTS, contract_for,  # noqa: E402
                                               summary)
from lpr_cpe_demo.northbound.samples import SAMPLES  # noqa: E402


def sample(name: str) -> dict:
    return copy.deepcopy(SAMPLES[name])


class TestProvenanceIsExplicit(unittest.TestCase):
    def test_the_standard_and_modelled_systems_are_named_exactly(self):
        """CRM joined in v1.22.0. TMF629 and TMF666 cover customer and billing
        account, but lifetime value, churn score and vulnerability flags are
        operator-specific and in no standard, so the system is marked MODELLED."""
        info = summary()
        self.assertEqual(set(info["standard"]), {"CPE", "WFM", "jTrack"})
        self.assertEqual(set(info["modelled"]), {"NXT", "CRM"})

    def test_nxt_is_modelled_end_to_end(self):
        nxt = contract_for("NXT")
        self.assertEqual(nxt.provenance, "MODELLED")
        for field in nxt.fields:
            self.assertEqual(field.provenance, "MODELLED", field.path)

    def test_the_crm_value_fields_are_marked_modelled_not_standard(self):
        """Only the account and agreement shapes come from TMF. Everything the
        ranking actually depends on is invented."""
        crm = contract_for("CRM")
        self.assertEqual(crm.provenance, "MODELLED")
        invented = {f.path for f in crm.fields if f.provenance == "MODELLED"}
        for field_name in ("monthlyRecurringRevenue", "churnScore",
                           "medicalOrSafetyFlag", "lifelineSubsidised"):
            self.assertIn(field_name, invented)

    def test_the_crm_protection_flags_say_they_are_protections(self):
        """Their absence silently removes a safeguard, so the contract must say so."""
        crm = contract_for("CRM")
        for field_name in ("medicalOrSafetyFlag", "vulnerabilityFlag",
                           "lifelineSubsidised"):
            spec = next(f for f in crm.fields if f.path == field_name)
            self.assertIn("PROTECTION", spec.note.upper())

    def test_every_standard_field_names_its_specification(self):
        for contract in CONTRACTS:
            if contract.provenance != "STANDARD":
                continue
            for field in contract.fields:
                self.assertTrue(field.source, f"{contract.system}.{field.path}")
                self.assertNotIn("MODELLED", field.source)

    def test_the_summary_carries_a_warning_about_nxt(self):
        self.assertIn("placeholder", summary()["warning"])

    def test_the_cpe_contract_uses_real_tr181_and_docsis_names(self):
        paths = {f.path for f in contract_for("CPE").fields}
        self.assertIn("Device.DeviceInfo.SerialNumber", paths)
        self.assertIn("docsIf3SignalQualityExtRxMER", paths)
        self.assertIn("Device.Optical.Interface.1.CurrentDownstreamRxPower", paths)

    def test_the_ticket_contract_uses_tmf621_status_names(self):
        contract = contract_for("jTrack")
        status = next(f for f in contract.fields if f.path == "status")
        self.assertIn("acknowledged", status.note)
        self.assertIn("TMF621", contract.specification)


class TestCpeScaling(unittest.TestCase):
    """The conversion integrations get wrong."""

    def test_docsis_values_are_scaled_from_tenths(self):
        result = parse_cpe_usp(sample("cpe_hfc"))
        self.assertAlmostEqual(result.kpis["ds_rx_dbmv"], -11.8)
        self.assertAlmostEqual(result.kpis["us_tx_dbmv"], 52.1)
        self.assertAlmostEqual(result.kpis["ds_mer_db"], 31.2)

    def test_optical_values_are_scaled_from_hundredths(self):
        result = parse_cpe_usp(sample("cpe_pon"))
        self.assertAlmostEqual(result.kpis["ont_rx_dbm"], -26.85)
        self.assertAlmostEqual(result.kpis["ont_tx_dbm"], 2.41)

    def test_an_unscaled_read_would_report_a_working_modem_as_dead(self):
        """-118 read as dBmV is catastrophic; as tenths it is -11.8 and in service."""
        raw = sample("cpe_hfc")["body"]["request"]["notify"]["event"]["params"]
        self.assertEqual(raw["docsIfDownChannelPower"], "-118")
        self.assertGreater(parse_cpe_usp(sample("cpe_hfc")).kpis["ds_rx_dbmv"], -15.0)

    def test_technology_is_inferred_from_the_parameters_present(self):
        self.assertEqual(parse_cpe_usp(sample("cpe_hfc")).technology, "HFC")
        self.assertEqual(parse_cpe_usp(sample("cpe_pon")).technology, "PON")

    def test_values_arriving_as_strings_are_accepted(self):
        """These systems send numbers as strings and always have."""
        self.assertIsInstance(parse_cpe_usp(sample("cpe_hfc")).kpis["ds_mer_db"],
                              float)

    def test_a_non_numeric_value_is_rejected_with_its_field_name(self):
        message = sample("cpe_hfc")
        message["body"]["request"]["notify"]["event"]["params"][
            "docsIf3SignalQualityExtRxMER"] = "n/a"
        with self.assertRaises(AdapterError) as ctx:
            parse_cpe_usp(message)
        self.assertIn("docsIf3SignalQualityExtRxMER", str(ctx.exception))

    def test_a_missing_serial_number_is_rejected(self):
        message = sample("cpe_hfc")
        del message["body"]["request"]["notify"]["event"]["params"][
            "Device.DeviceInfo.SerialNumber"]
        with self.assertRaises(AdapterError):
            parse_cpe_usp(message)

    def test_an_unknown_parameter_is_recorded_not_silently_dropped(self):
        message = sample("cpe_hfc")
        message["body"]["request"]["notify"]["event"]["params"][
            "vendorSecretSauce"] = "42"
        self.assertIn("vendorSecretSauce", parse_cpe_usp(message).rejected)

    def test_a_short_uptime_is_flagged_as_a_recent_reboot(self):
        self.assertTrue(parse_cpe_usp(sample("cpe_pon")).recently_rebooted)
        self.assertFalse(parse_cpe_usp(sample("cpe_hfc")).recently_rebooted)


class TestCounters(unittest.TestCase):
    def setUp(self):
        self.first = parse_cpe_usp(sample("cpe_hfc"))

    def _later(self, value: int, hours: float = 6.0) -> CpeSample:
        return CpeSample(self.first.modem_id, self.first.technology,
                         self.first.firmware, self.first.uptime_seconds,
                         self.first.observed_at + timedelta(hours=hours),
                         self.first.kpis, {"docsIfSigQUncorrectables": value})

    def test_a_rate_needs_two_samples(self):
        self.assertIsNone(counter_rate(self.first, self.first,
                                      "docsIfSigQUncorrectables"))

    def test_a_rate_is_computed_from_the_delta_over_time(self):
        rate = counter_rate(self.first, self._later(418223 + 900),
                            "docsIfSigQUncorrectables")
        self.assertAlmostEqual(rate, 3600.0, places=1)

    def test_a_counter_going_backwards_is_unknown_not_negative(self):
        """A reboot or a wrap. A negative rate would be meaningless."""
        self.assertIsNone(counter_rate(self.first, self._later(12),
                                      "docsIfSigQUncorrectables"))

    def test_a_zero_interval_yields_no_rate(self):
        self.assertIsNone(counter_rate(self.first, self._later(999999, hours=0.0),
                                      "docsIfSigQUncorrectables"))

    def test_an_absent_counter_yields_no_rate(self):
        self.assertIsNone(counter_rate(self.first, self._later(1),
                                      "docsIf3CmtsCmUsStatusT3Timeouts"))


class TestNxt(unittest.TestCase):
    def test_the_snapshot_parses(self):
        result = parse_nxt_snapshot(sample("nxt"))
        self.assertEqual(result.service_state, "degraded")
        self.assertTrue(result.degraded)
        self.assertEqual(result.delimiter_id, "TAP-ARE-AD00042")
        self.assertEqual(result.households_behind_delimiter, 6)

    def test_an_unknown_service_state_is_rejected(self):
        message = sample("nxt")
        message["serviceState"] = "wobbly"
        with self.assertRaises(AdapterError):
            parse_nxt_snapshot(message)

    def test_a_naive_timestamp_is_refused_rather_than_guessed(self):
        """Assuming a zone silently shifts every measurement by the offset."""
        message = sample("nxt")
        message["takenAt"] = "2026-08-18T03:59:02"
        with self.assertRaises(AdapterError) as ctx:
            parse_nxt_snapshot(message)
        self.assertIn("timezone", str(ctx.exception))

    def test_a_missing_required_field_names_itself(self):
        message = sample("nxt")
        del message["serviceId"]
        with self.assertRaises(AdapterError) as ctx:
            parse_nxt_snapshot(message)
        self.assertIn("serviceId", str(ctx.exception))

    def test_the_open_ticket_links_the_snapshot_to_jtrack(self):
        self.assertIn("JT-4471902", parse_nxt_snapshot(sample("nxt")).open_tickets)


class TestWfm(unittest.TestCase):
    def test_a_work_order_parses(self):
        order = parse_wfm_work_order(sample("wfm_order"))
        self.assertEqual(order.state, "acknowledged")
        self.assertEqual(order.crew_type, "dirty_boots")
        self.assertEqual(order.dispatch_base, "BASE-AGU")
        self.assertFalse(order.closed)

    def test_a_state_change_event_is_unwrapped(self):
        order = parse_wfm_work_order(sample("wfm_event"))
        self.assertEqual(order.state, "completed")
        self.assertTrue(order.closed)

    def test_the_no_fault_found_flag_is_parsed_from_a_string(self):
        order = parse_wfm_work_order(sample("wfm_event"))
        self.assertIs(order.no_fault_found, False)
        self.assertEqual(order.on_site_minutes, 165)

    def test_an_invalid_state_is_rejected(self):
        message = sample("wfm_order")
        message["state"] = "sortOfStarted"
        with self.assertRaises(AdapterError):
            parse_wfm_work_order(message)

    def test_operator_specific_fields_ride_in_characteristics(self):
        order = parse_wfm_work_order(sample("wfm_order"))
        self.assertEqual(order.characteristics["delimiterId"], "TAP-ARE-AD00042")


class TestJtrack(unittest.TestCase):
    def test_a_ticket_parses(self):
        ticket = parse_jtrack_ticket(sample("jtrack_ticket"))
        self.assertEqual(ticket.status, "inProgress")
        self.assertEqual(ticket.severity, "major")
        self.assertTrue(ticket.open)

    def test_the_predictive_origin_survives_the_round_trip(self):
        """A predictive ticket id must be traceable once it becomes a real one."""
        ticket = parse_jtrack_ticket(sample("jtrack_ticket"))
        self.assertEqual(ticket.predictive_ticket_id, "PRD-20260818-00515")

    def test_related_entities_are_resolved_by_role(self):
        ticket = parse_jtrack_ticket(sample("jtrack_ticket"))
        self.assertEqual(ticket.affected_service, "SVC-HFC-0099231")
        self.assertEqual(ticket.suspect_resource, "TAP-ARE-AD00042")

    def test_a_status_change_event_is_unwrapped(self):
        ticket = parse_jtrack_ticket(sample("jtrack_event"))
        self.assertEqual(ticket.status, "resolved")
        self.assertFalse(ticket.open)

    def test_a_non_tmf621_status_is_rejected(self):
        message = sample("jtrack_ticket")
        message["status"] = "sortOfFixed"
        with self.assertRaises(AdapterError):
            parse_jtrack_ticket(message)

    def test_a_non_tmf621_severity_is_rejected(self):
        message = sample("jtrack_ticket")
        message["severity"] = "quiteBad"
        with self.assertRaises(AdapterError):
            parse_jtrack_ticket(message)


class TestSystemsJoinUp(unittest.TestCase):
    """The four feeds have to agree on identifiers or none of this correlates."""

    def test_the_delimiter_is_the_same_across_nxt_wfm_and_jtrack(self):
        nxt = parse_nxt_snapshot(sample("nxt"))
        order = parse_wfm_work_order(sample("wfm_order"))
        ticket = parse_jtrack_ticket(sample("jtrack_ticket"))
        self.assertEqual(nxt.delimiter_id, order.delimiter_id)
        self.assertEqual(nxt.delimiter_id, ticket.suspect_resource)

    def test_the_nxt_snapshot_references_the_open_jtrack_ticket(self):
        nxt = parse_nxt_snapshot(sample("nxt"))
        ticket = parse_jtrack_ticket(sample("jtrack_ticket"))
        self.assertIn(ticket.ticket_id, nxt.open_tickets)

    def test_the_dispatch_base_is_one_the_geography_model_knows(self):
        from lpr_cpe_demo.geography import BASE_BY_ID
        order = parse_wfm_work_order(sample("wfm_order"))
        self.assertIn(order.dispatch_base, BASE_BY_ID)

    def test_the_generic_parse_entry_point_routes_by_system(self):
        self.assertEqual(parse("CPE", sample("cpe_hfc")).technology, "HFC")
        self.assertEqual(parse("jTrack", sample("jtrack_ticket")).status,
                         "inProgress")

    def test_an_unknown_system_is_rejected(self):
        with self.assertRaises(KeyError):
            parse("Skynet", {})
