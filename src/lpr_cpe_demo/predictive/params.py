"""Every tunable in the predictive branch, in one place.

Follows the convention used by `effort.RATES`, `plant.PLANT_ASSUMPTIONS` and
`geography.DISPATCH_BASES`: assumed values, a stated basis, and one place to
replace them. None of these came from LPR. They are plausible for a DOCSIS 3.1 and
XGS-PON estate and must be replaced with the operator's own thresholds before any
number leaves a demonstration.

The HFC thresholds follow the shape of the DOCSIS operational ranges commonly used
for PNM screening; the PON thresholds follow typical GPON and XGS-PON optical
budgets. Both are stated as the SHAPE of a rule, not as LPR's rule.
"""

from __future__ import annotations

from typing import Any

SCAN_PARAMS: dict[str, Any] = {
    "basis": ("plausible DOCSIS and PON operational ranges, not LPR thresholds; "
              "replace before any operational use"),

    # ---------------------------------------------------------------- schedule
    "run_hour_utc": 6,               # daily scan starts 06:00 UTC, 02:00 AST
    "remediation_window_utc": (6, 10),
    "window_note": ("Auto-remediation is confined to a window because a reboot "
                    "drops service for about two minutes. Outside it, tickets "
                    "queue rather than act."),

    # ------------------------------------------------------------------ estate
    "estate_sample": 25_000,         # modems scanned per run in the simulation
    "estate_note": ("A full footprint scan is ~1.22M locations. The simulation "
                    "samples, and `flag_rate_expected` is what matters for load."),

    # ----------------------------------------------------- proactive thresholds
    # Breached NOW, and no customer has called.
    "hfc": {
        "rx_dbmv_min": -12.0, "rx_dbmv_max": 12.0,
        "tx_dbmv_max": 51.0,
        "snr_db_min": 33.0,           # DOCSIS 3.1 OFDM, 4096-QAM headroom
        "uncorrectable_ratio_max": 1e-4,
        "t3_timeouts_max": 25,        # per day
        "flaps_max": 4,               # per day
    },
    "pon": {
        "rx_dbm_min": -27.0, "rx_dbm_max": -8.0,
        "tx_dbm_min": 0.5, "tx_dbm_max": 5.0,
        "ber_max": 1e-6,
        "los_events_max": 0,
        "dying_gasp_max": 1,
    },

    # ------------------------------------------------------------- forecasting
    "trend_window_days": 14,          # history used to fit the trend
    "forecast_horizon_days": 14,      # only forecast a crossing inside this
    "min_trend_r2": 0.55,             # fit quality floor; below this, no forecast
    "min_daily_drift": 0.02,          # ignore trends flatter than this per day
    "forecast_note": ("Least-squares fit on the degrading metric, extrapolated to "
                      "its failure threshold. A forecast is only issued when the "
                      "fit clears min_trend_r2 AND the crossing falls inside the "
                      "horizon, so a noisy flat modem cannot produce one."),

    # ----------------------------------------------------------------- urgency
    "urgency": {
        "proactive_degraded": "P2",   # already degraded, nobody has called
        "forecast_le_3_days": "P2",
        "forecast_le_7_days": "P3",
        "forecast_gt_7_days": "P4",
    },
    "sla_hours": {"P2": 24, "P3": 72, "P4": 168},
    "sla_note": ("Predictive SLA runs from when the SCAN opened the ticket, and "
                 "survives a later customer call attaching to it."),

    # ------------------------------------------------------- auto-remediation
    "auto_actions": ("remote_reprovision", "remote_reboot"),
    "max_auto_attempts": 2,
    "verify_after_minutes": 20,
    "auto_note": ("Auto-remediation runs BEFORE any human gate, which is what "
                  "activates PolicyVerdict.ALLOWED. It is attempted on both ticket "
                  "classes, including forecast tickets where the modem is still "
                  "working."),

    # ---------------------------------------------------------- notification
    "repeat_offender_days": 30,
    "notify_note": ("Three triggers only: a truck roll will be needed, a hard "
                    "failure is forecast inside the horizon, or the modem was "
                    "flagged again within repeat_offender_days. A "
                    "service-affecting auto-reboot alone does NOT notify."),
}


def sla_hours_for(urgency: str) -> int:
    return int(SCAN_PARAMS["sla_hours"].get(urgency, 168))
