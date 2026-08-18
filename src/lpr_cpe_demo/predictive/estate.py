"""Simulated modem estate and its daily telemetry.

Realism that matters for this branch
------------------------------------
A scan is only interesting if some modems are recoverable by a remote action and
some are not. Every modem therefore carries a **hidden true cause** that the scan
cannot see:

``healthy``          nothing wrong
``cpe_soft``         state corruption or a config drift. A reboot or reprovision
                     fixes it, so auto-remediation succeeds.
``cpe_hard``         failing hardware, a marginal tuner, a dying power supply. A
                     reboot masks it for hours and it returns, so auto-remediation
                     appears to work and then does not.
``plant``            the fault is at the drop, tap or ODP. A reboot cannot help,
                     so auto-remediation fails and a truck roll follows.

Without that distinction the auto-remediate-then-gate flow would never exercise
its own failure path, and the human gate would never fire for the reason the
operator cares about.

Degradation is a monotone drift plus noise, so a least-squares fit over a window
recovers a real trend for a degrading modem and a poor fit for a noisy healthy one.
That is what lets `scan.forecast` refuse to forecast on noise instead of producing
a confident number from nothing.

Everything is derived from a seed and a day index, so the same day reproduces
exactly and consecutive days form a coherent history.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Iterable, Literal

from ..geography import Site, sites_in_cpe_footprint
from ..plant import PLANT_ASSUMPTIONS, households
from .params import SCAN_PARAMS

Technology = Literal["HFC", "PON"]
TrueCause = Literal["healthy", "cpe_soft", "cpe_hard", "plant"]

# Population mix of the estate. Most modems are fine; the rest are split so that
# roughly half of the impaired ones are remotely recoverable, which is what makes
# the gate fire at a believable rate rather than never or always.
CAUSE_MIX: dict[TrueCause, float] = {
    "healthy": 0.958, "cpe_soft": 0.020, "cpe_hard": 0.012, "plant": 0.010,
}

# How far a cause drives each metric per day, in the direction of failure.
DRIFT: dict[TrueCause, float] = {
    "healthy": 0.0, "cpe_soft": 0.22, "cpe_hard": 0.30, "plant": 0.38,
}


@dataclass(frozen=True, slots=True)
class Modem:
    modem_id: str
    site_id: str
    municipio: str
    archetype: str
    technology: Technology
    true_cause: TrueCause
    onset_day: int          # day index at which degradation began
    noise: float            # per-modem measurement noise


@dataclass(frozen=True, slots=True)
class Reading:
    modem_id: str
    day: int
    technology: Technology
    metrics: dict[str, float]
    customer_contacted: bool


def _rng(*parts: object) -> random.Random:
    material = "|".join(str(p) for p in parts).encode()
    return random.Random(int(hashlib.sha256(material).hexdigest()[:12], 16))


def build_estate(count: int | None = None, *, seed: int = 20260817,
                 sites: Iterable[Site] | None = None) -> list[Modem]:
    """Sample an estate, weighting sites by household count as elsewhere."""
    count = count or int(SCAN_PARAMS["estate_sample"])
    rng = random.Random(seed)
    pool = list(sites if sites is not None else sites_in_cpe_footprint())
    weights = [max(1, households(s)) for s in pool]

    causes = list(CAUSE_MIX)
    cause_weights = [CAUSE_MIX[c] for c in causes]

    estate: list[Modem] = []
    for index in range(count):
        site = rng.choices(pool, weights=weights, k=1)[0]
        pon_share = float(PLANT_ASSUMPTIONS["pon_share_by_archetype"][site.archetype])  # type: ignore[index]
        technology: Technology = "PON" if rng.random() < pon_share else "HFC"
        cause: TrueCause = rng.choices(causes, weights=cause_weights, k=1)[0]
        estate.append(Modem(
            modem_id=f"CM-{site.site_id.split('-')[1]}-{index:06d}",
            site_id=site.site_id, municipio=site.municipio,
            archetype=site.archetype, technology=technology,
            true_cause=cause,
            # A degrading modem started somewhere in the recent past, so on any
            # given day the estate contains trends of varying maturity.
            onset_day=0 if cause == "healthy" else rng.randint(-40, 2),
            noise=round(rng.uniform(0.35, 1.15), 3)))
    return estate


def _severity(modem: Modem, day: int) -> float:
    """How far along its degradation a modem is on this day, 0 upward."""
    if modem.true_cause == "healthy":
        return 0.0
    elapsed = day - modem.onset_day
    if elapsed <= 0:
        return 0.0
    return DRIFT[modem.true_cause] * elapsed


def read(modem: Modem, day: int, *, seed: int = 20260817,
         remediated_on: int | None = None) -> Reading:
    """One day's telemetry.

    `remediated_on` models the effect of a successful remote action: a `cpe_soft`
    modem is reset to healthy from that day, while `cpe_hard` recovers briefly and
    resumes, and `plant` is unaffected. This is what makes verification after
    remediation meaningful rather than a formality.
    """
    rng = _rng(seed, modem.modem_id, day)
    severity = _severity(modem, day)

    if remediated_on is not None and day >= remediated_on:
        since = day - remediated_on
        if modem.true_cause == "cpe_soft":
            severity = 0.0
        elif modem.true_cause == "cpe_hard":
            # masked for about two days, then resumes from where it left off
            severity = 0.0 if since < 2 else severity * 0.75
        # plant: unchanged, a reboot cannot move it

    jitter = lambda scale=1.0: rng.gauss(0.0, modem.noise * scale)  # noqa: E731

    if modem.technology == "HFC":
        metrics = {
            "rx_dbmv": round(1.5 - severity * 1.1 + jitter(0.7), 2),
            "tx_dbmv": round(44.0 + severity * 0.9 + jitter(0.5), 2),
            "snr_db": round(40.0 - severity * 0.85 + jitter(0.45), 2),
            "uncorrectable_ratio": round(
                max(0.0, 1e-6 + severity * 2.2e-5 + abs(jitter(0.2)) * 4e-6), 9),
            "t3_timeouts": max(0, int(severity * 3.4 + abs(jitter(1.4)))),
            "flaps": max(0, int(severity * 0.7 + abs(jitter(0.5)))),
        }
    else:
        metrics = {
            "rx_dbm": round(-19.0 - severity * 0.95 + jitter(0.5), 2),
            "tx_dbm": round(2.4 + severity * 0.12 + jitter(0.15), 2),
            "ber": round(max(0.0, 1e-9 + severity * 2.4e-7 + abs(jitter(0.2)) * 3e-8), 12),
            "los_events": max(0, int(severity * 0.35 + abs(jitter(0.3)) - 0.4)),
            "dying_gasp": max(0, int(severity * 0.22 + abs(jitter(0.25)) - 0.5)),
        }

    # A degraded modem sometimes prompts a call. Proactive detection is defined as
    # a breach with NO customer contact, so this is what the scan must exclude.
    contacted = severity > 6.0 and rng.random() < 0.30
    return Reading(modem.modem_id, day, modem.technology, metrics, contacted)


def history(modem: Modem, end_day: int, days: int | None = None, *,
            seed: int = 20260817,
            remediated_on: int | None = None) -> list[Reading]:
    """Readings for the trend window ending on `end_day`, oldest first."""
    days = days or int(SCAN_PARAMS["trend_window_days"])
    return [read(modem, day, seed=seed, remediated_on=remediated_on)
            for day in range(end_day - days + 1, end_day + 1)]


# Which metric drives failure for each technology, and the value it fails at.
# `worsens_upward` says which direction is bad, so one fit routine handles both.
FAILURE_METRIC: dict[str, dict[str, object]] = {
    "HFC": {"metric": "snr_db",
            "threshold": float(SCAN_PARAMS["hfc"]["snr_db_min"]),
            "worsens_upward": False,
            "hard_failure_at": 26.0},
    "PON": {"metric": "rx_dbm",
            "threshold": float(SCAN_PARAMS["pon"]["rx_dbm_min"]),
            "worsens_upward": False,
            "hard_failure_at": -30.0},
}


def linear_fit(values: list[float]) -> tuple[float, float, float]:
    """Least squares on evenly spaced points. Returns slope, intercept, r squared.

    Pure Python so the forecast is testable without numpy, and so the fit quality
    can be asserted rather than trusted.
    """
    n = len(values)
    if n < 3:
        return 0.0, (values[-1] if values else 0.0), 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, mean_y, 0.0
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in values)
    if ss_tot == 0:
        return slope, intercept, 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
    return slope, intercept, max(0.0, 1.0 - ss_res / ss_tot)
