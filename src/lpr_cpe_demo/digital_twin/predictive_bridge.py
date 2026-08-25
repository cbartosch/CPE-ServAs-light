from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# The production host already contains lpr_cpe_demo.predictive. Hotfix5 uses that
# scanner when available. The small compatible fallback keeps the standalone
# Digital Twin bundle executable and testable without copying the host package.
try:  # pragma: no cover - exercised only in the integrated host repository
    from lpr_cpe_demo.predictive.config import ScanConfig as HostScanConfig
    from lpr_cpe_demo.predictive.scanner import scan as host_scan
    from lpr_cpe_demo.predictive.signals import ModemSeries as HostModemSeries

    HOST_PREDICTIVE_AVAILABLE = True
except (ImportError, ModuleNotFoundError):  # standalone release
    HostScanConfig = None  # type: ignore[assignment,misc]
    host_scan = None  # type: ignore[assignment]
    HostModemSeries = None  # type: ignore[assignment,misc]
    HOST_PREDICTIVE_AVAILABLE = False

HFC_KPIS = (
    "ds_rx_dbmv",
    "us_tx_dbmv",
    "ds_mer_db",
    "uncorrectable_ratio",
    "t3_timeouts_per_day",
)
PON_KPIS = ("ont_rx_dbm", "ont_tx_dbm", "ber", "dying_gasp_per_day")

THRESHOLDS: dict[str, tuple[float, str]] = {
    "ds_rx_dbmv": (-15.0, "falling"),
    "us_tx_dbmv": (55.0, "rising"),
    "ds_mer_db": (30.0, "falling"),
    "uncorrectable_ratio": (1e-4, "rising"),
    "t3_timeouts_per_day": (25.0, "rising"),
    "ont_rx_dbm": (-27.0, "falling"),
    "ont_tx_dbm": (-1.0, "falling"),
    "ber": (1e-6, "rising"),
    "dying_gasp_per_day": (4.0, "rising"),
}

BASELINES: dict[str, float] = {
    "ds_rx_dbmv": 0.5,
    "us_tx_dbmv": 44.0,
    "ds_mer_db": 38.5,
    "uncorrectable_ratio": 2e-8,
    "t3_timeouts_per_day": 0.3,
    "ont_rx_dbm": -19.5,
    "ont_tx_dbm": 2.6,
    "ber": 1e-11,
    "dying_gasp_per_day": 0.05,
}

SCENARIO_SIGNAL: dict[str, str] = {
    "no_service": "hard_loss",
    "intermittent_service": "intermittent",
    "iptv_degradation": "quality",
    "fiber_cut": "hard_loss",
    "hfc_ingress": "quality",
    "power_outage": "hard_loss",
    "storm": "hard_loss",
    "flooding": "hard_loss",
    "hurricane": "hard_loss",
    "provisioning_error": "provisioning",
    "cpe_failure": "intermittent",
    # Slow Wi-Fi and shared congestion are intentionally not forced into an access
    # plant KPI; the modem scan may correctly have no predictive match for them.
    "slow_wifi": "none",
    "congestion": "none",
}


@dataclass(frozen=True, slots=True)
class FallbackSeries:
    modem_id: str
    site_id: str
    technology: str
    cause: str
    kpis: dict[str, tuple[float, ...]]


@dataclass(frozen=True, slots=True)
class PredictiveSnapshot:
    scan_id: str
    ran_at: datetime
    engine: str
    scanned: int
    healthy: int
    pulls: list[dict]
    tickets: list[dict]

    def summary(self) -> dict[str, object]:
        by_class: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for ticket in self.tickets:
            cls = str(ticket["ticket_class"])
            sev = str(ticket["severity"])
            by_class[cls] = by_class.get(cls, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1
        return {
            "scan_id": self.scan_id,
            "ran_at": self.ran_at.isoformat(),
            "engine": self.engine,
            "scanned": self.scanned,
            "healthy": self.healthy,
            "tickets": len(self.tickets),
            "flag_rate": round(len(self.tickets) / self.scanned, 5) if self.scanned else 0.0,
            "by_class": by_class,
            "by_severity": by_severity,
        }


def _stable_rng(*parts: object) -> random.Random:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _linear_trend(values: Sequence[float]) -> tuple[float, float, float]:
    n = len(values)
    if n < 2:
        return 0.0, (values[0] if values else 0.0), 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    sxx = sum((index - mean_x) ** 2 for index in range(n))
    sxy = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
    if sxx == 0:
        return 0.0, mean_y, 0.0
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    total = sum((value - mean_y) ** 2 for value in values)
    if total == 0:
        return slope, intercept, 1.0
    residual = sum(
        (value - (slope * index + intercept)) ** 2 for index, value in enumerate(values)
    )
    return slope, intercept, max(0.0, 1.0 - residual / total)


def _days_to_threshold(values: Sequence[float], threshold: float, direction: str) -> float | None:
    slope, intercept, _ = _linear_trend(values)
    current = slope * (len(values) - 1) + intercept
    if direction == "falling":
        if current <= threshold or slope >= -1e-12:
            return None
    elif current >= threshold or slope <= 1e-12:
        return None
    days = (threshold - current) / slope
    return days if days > 0 and math.isfinite(days) else None


def _technology(value: str) -> str:
    return "HFC" if value == "HFC" else "PON"


def _scenario_pattern(scenario: str | None, index: int) -> str:
    if scenario:
        return SCENARIO_SIGNAL.get(scenario, "none")
    if index % 97 == 0:
        return "hard_loss"
    if index % 53 == 0:
        return "forecast"
    return "none"


def _series_for(subscriber: dict, *, days: int, seed: int, scenario: str | None, index: int):
    technology = _technology(str(subscriber["technology"]))
    kpis = HFC_KPIS if technology == "HFC" else PON_KPIS
    rng = _stable_rng(seed, subscriber["device_id"], scenario or "background")
    pattern = _scenario_pattern(scenario, index)
    values: dict[str, tuple[float, ...]] = {}

    for kpi in kpis:
        baseline = BASELINES[kpi]
        jitter = 0.2 if abs(baseline) > 1 else max(abs(baseline) * 0.02, 1e-10)
        samples = [baseline + rng.uniform(-jitter, jitter) for _ in range(days)]
        values[kpi] = tuple(round(value, 10) for value in samples)

    if pattern in {"hard_loss", "forecast", "quality", "intermittent", "provisioning"}:
        if technology == "HFC":
            if pattern == "quality":
                key, start, end = "ds_mer_db", 35.0, 28.8
            elif pattern == "intermittent":
                key, start, end = "t3_timeouts_per_day", 4.0, 29.0
            elif pattern == "provisioning":
                key, start, end = "us_tx_dbmv", 47.0, 56.0
            elif pattern == "forecast":
                key, start, end = "ds_mer_db", 36.0, 31.2
            else:
                key, start, end = "ds_rx_dbmv", -8.5, -16.2
        else:
            if pattern == "quality":
                key, start, end = "ber", 1e-9, 1.4e-6
            elif pattern == "intermittent":
                key, start, end = "dying_gasp_per_day", 0.4, 4.8
            elif pattern == "provisioning":
                key, start, end = "ont_tx_dbm", 2.0, -1.4
            elif pattern == "forecast":
                key, start, end = "ont_rx_dbm", -22.0, -25.8
            else:
                key, start, end = "ont_rx_dbm", -23.0, -27.8
        delta = (end - start) / max(1, days - 1)
        values[key] = tuple(round(start + delta * day, 10) for day in range(days))

    cause = pattern if pattern != "none" else "stable"
    if HOST_PREDICTIVE_AVAILABLE:
        assert HostModemSeries is not None
        host_cause = {
            "hard_loss": "plant",
            "forecast": "plant",
            "quality": "tap_or_odp",
            "intermittent": "cpe_state",
            "provisioning": "config_drift",
            "none": "stable",
            "stable": "stable",
        }.get(cause, "plant")
        return HostModemSeries(
            subscriber["device_id"],
            subscriber["delimiter_id"],
            technology,
            host_cause,
            values,
        )
    return FallbackSeries(
        modem_id=subscriber["device_id"],
        site_id=subscriber["delimiter_id"],
        technology=technology,
        cause=cause,
        kpis=values,
    )


def _fallback_ticket_rows(series_list: Sequence[FallbackSeries], ran_at: datetime, scan_id: str):
    tickets: list[dict] = []
    healthy = 0
    for index, series in enumerate(series_list):
        findings: list[dict] = []
        for kpi, values in series.kpis.items():
            threshold, direction = THRESHOLDS[kpi]
            current = values[-1]
            breached = current <= threshold if direction == "falling" else current >= threshold
            slope, _, r_squared = _linear_trend(values)
            eta = None
            if not breached and r_squared >= 0.55:
                eta = _days_to_threshold(values, threshold, direction)
                if eta is not None and eta > 14:
                    eta = None
            if breached or eta is not None:
                findings.append(
                    {
                        "kpi": kpi,
                        "value": round(current, 10),
                        "threshold": threshold,
                        "direction": direction,
                        "breached_now": breached,
                        "days_to_breach": None if eta is None else round(eta, 2),
                        "slope_per_day": round(slope, 6),
                        "r_squared": round(r_squared, 4),
                    }
                )
        if not findings:
            healthy += 1
            continue
        proactive = any(item["breached_now"] for item in findings)
        ticket_class = "proactive" if proactive else "forecast"
        if proactive:
            severity = "critical" if len(findings) >= 2 else "high"
            sla_hours = 24
        else:
            soonest = min(
                float(item["days_to_breach"])
                for item in findings
                if item["days_to_breach"] is not None
            )
            severity = "high" if soonest <= 3 else "medium" if soonest <= 7 else "low"
            sla_hours = 120
        tickets.append(
            {
                "ticket_id": f"PRD-{scan_id}-{index + 1:05d}",
                "modem_id": series.modem_id,
                "site_id": series.site_id,
                "technology": series.technology,
                "ticket_class": ticket_class,
                "severity": severity,
                "opened_at": ran_at.isoformat(),
                "sla_due_at": (ran_at + timedelta(hours=sla_hours)).isoformat(),
                "findings": findings,
                "suspected_cause": series.cause,
                "repeat_offender": False,
                "previous_flags": 0,
                "scan_run_id": scan_id,
            }
        )
    return tickets, healthy


def build_snapshot(
    subscribers: Iterable[dict],
    *,
    scenario_by_service: dict[str, str],
    ran_at: datetime,
    seed: int,
    days: int = 14,
    scan_id: str | None = None,
) -> PredictiveSnapshot:
    """Run a predictive modem pull using the host scanner when it is installed."""
    ordered = list(subscribers)
    identifier = scan_id or ran_at.astimezone(UTC).strftime("SCAN-%Y%m%dT%H%M%SZ")
    series_list = [
        _series_for(
            subscriber,
            days=days,
            seed=seed,
            scenario=scenario_by_service.get(str(subscriber["service_id"])),
            index=index,
        )
        for index, subscriber in enumerate(ordered)
    ]

    if HOST_PREDICTIVE_AVAILABLE:
        assert host_scan is not None and HostScanConfig is not None
        config = HostScanConfig(
            population=len(series_list),
            trend_window_days=days,
            min_samples_for_trend=min(7, days),
            max_tickets_per_run=max(400, len(series_list)),
        )
        result = host_scan(series_list, run_id=identifier, ran_at=ran_at, config=config)
        tickets = []
        for ticket in result.tickets:
            tickets.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "modem_id": ticket.modem_id,
                    "site_id": ticket.site_id,
                    "technology": ticket.technology,
                    "ticket_class": ticket.ticket_class,
                    "severity": ticket.severity,
                    "opened_at": ticket.opened_at.isoformat(),
                    "sla_due_at": ticket.sla_due_at.isoformat(),
                    "findings": [
                        {
                            "kpi": finding.kpi,
                            "value": finding.value,
                            "threshold": finding.threshold,
                            "direction": finding.direction,
                            "breached_now": finding.breached_now,
                            "days_to_breach": finding.days_to_breach,
                            "slope_per_day": finding.slope_per_day,
                            "r_squared": finding.r_squared,
                        }
                        for finding in ticket.findings
                    ],
                    "suspected_cause": ticket.suspected_cause,
                    "repeat_offender": ticket.repeat_offender,
                    "previous_flags": ticket.previous_flags,
                    "scan_run_id": ticket.scan_run_id,
                }
            )
        healthy = result.healthy
        engine = "lpr_cpe_demo.predictive.scanner"
    else:
        tickets, healthy = _fallback_ticket_rows(series_list, ran_at, identifier)
        engine = "digital_twin.compatible_predictive_fallback"

    subscriber_by_device = {str(sub["device_id"]): sub for sub in ordered}
    pulls: list[dict] = []
    for series in series_list:
        sub = subscriber_by_device[series.modem_id]
        summaries = {}
        for kpi, values in series.kpis.items():
            slope, _, r_squared = _linear_trend(values)
            summaries[kpi] = {
                "first": values[0],
                "latest": values[-1],
                "slope_per_day": round(slope, 6),
                "r_squared": round(r_squared, 4),
                "samples": len(values),
            }
        pulls.append(
            {
                "pull_id": f"PULL-{identifier}-{sub['device_id']}",
                "scan_id": identifier,
                "scan_timestamp": ran_at.isoformat(),
                "service_id": sub["service_id"],
                "device_id": sub["device_id"],
                "serial_number": sub["serial_number"],
                "mac_address": sub["mac_address"],
                "technology": sub["technology"],
                "delimiter_type": sub["delimiter_type"],
                "delimiter_id": sub["delimiter_id"],
                "source_system": "SYNTHETIC_TR069_TR181_NXT_ADAPTER",
                "engine": engine,
                "trend_window_days": days,
                "signal_profile": scenario_by_service.get(str(sub["service_id"]), "background"),
                "kpis": summaries,
            }
        )

    service_by_device = {str(sub["device_id"]): str(sub["service_id"]) for sub in ordered}
    for ticket in tickets:
        ticket["scan_id"] = identifier
        ticket["service_id"] = service_by_device[ticket["modem_id"]]
        ticket["device_id"] = ticket.pop("modem_id")
        ticket["source_system"] = "PREDICTIVE_MODEM_SCAN"
        ticket["engine"] = engine

    return PredictiveSnapshot(
        scan_id=identifier,
        ran_at=ran_at,
        engine=engine,
        scanned=len(series_list),
        healthy=healthy,
        pulls=pulls,
        tickets=tickets,
    )
