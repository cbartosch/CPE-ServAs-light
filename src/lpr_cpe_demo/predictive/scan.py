"""Classify a modem into a ticket class, or leave it alone.

Two classes, as agreed
----------------------
``PROACTIVE``  a threshold is breached NOW and no customer has called. The scan is
               getting there first.
``FORECAST``   nothing is breached yet, but the degrading metric is trending toward
               its failure threshold and will cross inside the horizon.

Order matters: a modem already in breach is PROACTIVE, not FORECAST, because a
prediction about something that has already happened is not a prediction.

Why a forecast can be refused
-----------------------------
A forecast is only issued when three conditions hold together: the fit clears
`min_trend_r2`, the drift exceeds `min_daily_drift`, and the projected crossing
falls inside `forecast_horizon_days`. A healthy modem fits at r squared near zero,
so it cannot produce a confident crossing from noise. That refusal is the point —
without it the scan would emit a plausible number for every modem on the estate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .estate import FAILURE_METRIC, Modem, Reading, linear_fit
from .params import SCAN_PARAMS

TicketClass = Literal["proactive", "forecast"]


@dataclass(frozen=True, slots=True)
class Breach:
    metric: str
    value: float
    limit: float
    direction: str          # "below" | "above"

    def describe(self) -> str:
        return (f"{self.metric} {self.value:g} is {self.direction} "
                f"the {self.limit:g} limit")


@dataclass(frozen=True, slots=True)
class Finding:
    modem_id: str
    site_id: str
    municipio: str
    archetype: str
    technology: str
    ticket_class: TicketClass
    urgency: str
    breaches: tuple[Breach, ...] = ()
    # forecast only
    days_to_failure: float | None = None
    trend_slope: float | None = None
    trend_r2: float | None = None
    hard_failure: bool = False
    evidence: tuple[str, ...] = ()

    @property
    def is_forecast(self) -> bool:
        return self.ticket_class == "forecast"


def _limits(technology: str) -> list[tuple[str, float, str]]:
    """(metric, limit, direction) triples for the proactive thresholds."""
    p = SCAN_PARAMS["hfc"] if technology == "HFC" else SCAN_PARAMS["pon"]
    out: list[tuple[str, float, str]] = []
    for key, limit in p.items():
        if key.endswith("_min"):
            out.append((key[:-4], float(limit), "below"))
        elif key.endswith("_max"):
            out.append((key[:-4], float(limit), "above"))
    return out


def breaches_for(reading: Reading) -> tuple[Breach, ...]:
    found: list[Breach] = []
    for metric, limit, direction in _limits(reading.technology):
        if metric not in reading.metrics:
            continue
        value = float(reading.metrics[metric])
        if direction == "below" and value < limit:
            found.append(Breach(metric, value, limit, "below"))
        elif direction == "above" and value > limit:
            found.append(Breach(metric, value, limit, "above"))
    return tuple(found)


def forecast(modem: Modem, readings: list[Reading]) -> tuple[float, float, float] | None:
    """Days until the failure threshold is crossed, plus slope and fit quality.

    Returns None when the trend does not justify a claim, which is the common case
    and the important one.
    """
    spec = FAILURE_METRIC[modem.technology]
    metric = str(spec["metric"])
    values = [float(r.metrics[metric]) for r in readings if metric in r.metrics]
    if len(values) < 4:
        return None

    slope, _, r2 = linear_fit(values)
    if r2 < float(SCAN_PARAMS["min_trend_r2"]):
        return None
    if abs(slope) < float(SCAN_PARAMS["min_daily_drift"]):
        return None

    threshold = float(spec["threshold"])
    worsens_upward = bool(spec["worsens_upward"])
    current = values[-1]

    # The trend must be moving the wrong way, not merely moving.
    if worsens_upward and slope <= 0:
        return None
    if not worsens_upward and slope >= 0:
        return None

    remaining = (threshold - current) / slope
    if remaining <= 0:
        return None                      # already crossed; that is a breach
    if remaining > float(SCAN_PARAMS["forecast_horizon_days"]):
        return None
    return remaining, slope, r2


def _urgency_for_days(days: float) -> str:
    u = SCAN_PARAMS["urgency"]
    if days <= 3:
        return str(u["forecast_le_3_days"])
    if days <= 7:
        return str(u["forecast_le_7_days"])
    return str(u["forecast_gt_7_days"])


def classify(modem: Modem, readings: list[Reading]) -> Finding | None:
    """One modem, one day. Returns a Finding or None if nothing is wrong."""
    if not readings:
        return None
    latest = readings[-1]

    breaches = breaches_for(latest)
    if breaches:
        # Proactive detection is defined by the ABSENCE of a customer call. If the
        # customer has already called, this belongs to the reactive flow and the
        # scan must not open a second ticket for it.
        if latest.customer_contacted:
            return None
        return Finding(
            modem_id=modem.modem_id, site_id=modem.site_id,
            municipio=modem.municipio, archetype=modem.archetype,
            technology=modem.technology, ticket_class="proactive",
            urgency=str(SCAN_PARAMS["urgency"]["proactive_degraded"]),
            breaches=breaches,
            evidence=tuple(b.describe() for b in breaches))

    projected = forecast(modem, readings)
    if projected is None:
        return None
    days, slope, r2 = projected

    spec = FAILURE_METRIC[modem.technology]
    metric = str(spec["metric"])
    current = float(latest.metrics[metric])
    hard_at = float(spec["hard_failure_at"])
    # A hard failure is a crossing of the harder limit, not merely the alarm one,
    # projected within the same horizon.
    hard_days = (hard_at - current) / slope if slope else float("inf")
    hard = 0 < hard_days <= float(SCAN_PARAMS["forecast_horizon_days"])

    return Finding(
        modem_id=modem.modem_id, site_id=modem.site_id,
        municipio=modem.municipio, archetype=modem.archetype,
        technology=modem.technology, ticket_class="forecast",
        urgency=_urgency_for_days(days),
        days_to_failure=round(days, 1), trend_slope=round(slope, 4),
        trend_r2=round(r2, 3), hard_failure=hard,
        evidence=(f"{metric} trending {slope:+.3f} per day, fit r2 {r2:.2f}",
                  f"projected to cross {spec['threshold']} in {days:.1f} days",
                  f"hard failure at {hard_at:g} "
                  f"{'inside' if hard else 'outside'} the horizon"))
