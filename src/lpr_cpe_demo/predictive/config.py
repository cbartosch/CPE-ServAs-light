"""Assumed parameters for the predictive scan, in one replaceable place.

Every value here is ASSUMED. Thresholds follow published DOCSIS 3.1 and GPON
operating ranges, which is the closest thing to a defensible starting point, but
LPR's own alarm points, scan volume and window will differ. Replace this module,
not the code that reads it.

`basis` on each group states where the number came from, in the same way as
`effort.RATES` and `plant.PLANT_ASSUMPTIONS`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TicketClass = Literal["forecast", "proactive"]

# --------------------------------------------------------------------- HFC
# DOCSIS 3.1 operating ranges. Downstream Rx and upstream Tx in dBmV, MER in dB.
HFC_THRESHOLDS: dict[str, dict[str, float]] = {
    "ds_rx_dbmv": {"target": 0.0, "warn_low": -10.0, "alarm_low": -15.0,
                   "warn_high": 10.0, "alarm_high": 15.0},
    "us_tx_dbmv": {"target": 45.0, "warn_low": 35.0, "alarm_low": 30.0,
                   "warn_high": 51.0, "alarm_high": 55.0},
    "ds_mer_db": {"target": 38.0, "warn_low": 33.0, "alarm_low": 30.0},
    "uncorrectable_ratio": {"target": 0.0, "warn_high": 1e-6, "alarm_high": 1e-4},
    "t3_timeouts_per_day": {"target": 0.0, "warn_high": 5.0, "alarm_high": 25.0},
}

# --------------------------------------------------------------------- PON
# GPON ONT optical budget. Rx and Tx in dBm.
PON_THRESHOLDS: dict[str, dict[str, float]] = {
    "ont_rx_dbm": {"target": -20.0, "warn_low": -25.0, "alarm_low": -27.0,
                   "warn_high": -8.0, "alarm_high": -6.0},
    "ont_tx_dbm": {"target": 2.5, "warn_low": 0.5, "alarm_low": -1.0,
                   "warn_high": 5.0, "alarm_high": 7.0},
    "ber": {"target": 0.0, "warn_high": 1e-9, "alarm_high": 1e-6},
    "dying_gasp_per_day": {"target": 0.0, "warn_high": 1.0, "alarm_high": 4.0},
}

THRESHOLD_BASIS = ("published DOCSIS 3.1 and GPON operating ranges, not LPR "
                   "alarm points")


@dataclass(frozen=True, slots=True)
class ScanConfig:
    """One daily scan."""

    # Population. The full footprint is far larger; a scan of every modem is a
    # batch job, and the demo samples a slice of it.
    population: int = 20_000
    trend_window_days: int = 14
    min_samples_for_trend: int = 7

    # Forecast horizon. A modem whose trend reaches an alarm threshold inside this
    # many days becomes a forecast ticket.
    forecast_horizon_days: int = 14
    # A trend must explain enough of the variance to be worth acting on, or every
    # noisy modem produces a ticket.
    min_trend_r2: float = 0.55

    # Repeat offender: same modem flagged again within this many days.
    repeat_window_days: int = 30

    # When the scan runs, and when a service-affecting remediation may execute.
    # This is load-bearing: the operator chose to auto-reboot a working modem
    # WITHOUT notifying the customer, so the window is what keeps that acceptable.
    scan_hour_local: int = 4
    maintenance_window_start_hour: int = 1
    maintenance_window_end_hour: int = 5

    # SLA by class, in hours from when the scan opened the ticket.
    sla_hours: dict[str, int] = field(
        default_factory=lambda: {"proactive": 24, "forecast": 120})

    # Cap on tickets raised per run, so a systemic plant event does not create
    # thousands of individual modem tickets.
    max_tickets_per_run: int = 400

    basis: str = ("population, window, horizon and caps are assumed; thresholds "
                  "follow published DOCSIS and GPON ranges")

    def in_maintenance_window(self, hour: int) -> bool:
        start, end = self.maintenance_window_start_hour, self.maintenance_window_end_hour
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end          # window crosses midnight


@dataclass(frozen=True, slots=True)
class RemediationConfig:
    """What the branch may do without asking, and how well it works.

    Success rates are ASSUMED. They encode a real constraint rather than a guess
    about vendors: a remote action cannot fix a physical fault. A reboot clears
    transient CPE state; a reprovision clears configuration drift; neither repairs
    a corroded tap or a contaminated splitter, so both fail against a physical
    root cause and the ticket escalates.
    """

    max_auto_attempts: int = 2
    reboot_service_interruption_minutes: int = 2

    # Probability the action resolves the ticket, given the true root cause.
    success_by_cause: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "cpe_state":     {"remote_reboot": 0.82, "remote_reprovision": 0.35},
        "config_drift":  {"remote_reboot": 0.20, "remote_reprovision": 0.88},
        "firmware":      {"remote_reboot": 0.45, "remote_reprovision": 0.25},
        "wifi_env":      {"remote_reboot": 0.30, "remote_reprovision": 0.15},
        "drop":          {"remote_reboot": 0.02, "remote_reprovision": 0.01},
        "tap_or_odp":    {"remote_reboot": 0.01, "remote_reprovision": 0.01},
        "plant":         {"remote_reboot": 0.01, "remote_reprovision": 0.01},
    })
    basis: str = "assumed success rates; physical causes are deliberately near zero"


# KPIs whose alarm bound means the service DROPS, not merely degrades.
#
# DEFINITION I HAD TO MAKE CONCRETE, FLAGGED FOR CONFIRMATION.
# "Notify when a hard failure is forecast inside the horizon" is vacuous if
# "hard failure" means any threshold breach, because the scanner only raises a
# forecast ticket when a breach falls inside the horizon: every forecast ticket
# would notify. Read as loss of service it discriminates.
#
# Below alarm_low downstream Rx, the modem cannot hold lock. Above alarm_high
# upstream Tx, it cannot reach the CMTS at all. Below alarm_low ONT Rx is loss of
# signal. The rest -- MER, codeword errors, BER, T3 timeouts, dying gasp -- are
# degradation: slower, lossy, but still in service.
HARD_FAILURE_KPIS = frozenset({"ds_rx_dbmv", "us_tx_dbmv", "ont_rx_dbm"})

# Causes a remote action cannot fix. Reaching one of these means a truck roll,
# which is itself a notification trigger.
PHYSICAL_CAUSES = frozenset({"drop", "tap_or_odp", "plant"})

DEFAULT_SCAN = ScanConfig()
DEFAULT_REMEDIATION = RemediationConfig()


def assumptions() -> dict[str, object]:
    return {
        "scan": {k: getattr(DEFAULT_SCAN, k) for k in
                 ("population", "trend_window_days", "forecast_horizon_days",
                  "min_trend_r2", "repeat_window_days", "scan_hour_local",
                  "maintenance_window_start_hour", "maintenance_window_end_hour",
                  "max_tickets_per_run")},
        "sla_hours": dict(DEFAULT_SCAN.sla_hours),
        "hfc_thresholds": HFC_THRESHOLDS,
        "pon_thresholds": PON_THRESHOLDS,
        "threshold_basis": THRESHOLD_BASIS,
        "remediation_basis": DEFAULT_REMEDIATION.basis,
        "scan_basis": DEFAULT_SCAN.basis,
    }
