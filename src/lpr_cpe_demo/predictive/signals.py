"""Synthetic modem telemetry with degradation trajectories.

The data contract records that CMTS/PNM and OLT EMS collectors are not wired, so
this generates the series a scan would otherwise read. It is a simulation, and
`DATA_CONTRACT` names the systems that would replace it.

What makes it realistic rather than random
------------------------------------------
A scan that flags modems at random is indistinguishable from one that works, so
each modem carries a latent root cause and a trajectory consistent with it:

* `stable` sits near target with measurement noise only.
* `config_drift` and `firmware` show step changes, not slopes: a reprovision or a
  firmware push moves a value and it stays moved.
* `drop`, `tap_or_odp` and `plant` degrade monotonically, because water ingress,
  corrosion and connector contamination get worse. These are the trajectories a
  forecast should catch, and the ones a remote action cannot fix.
* `cpe_state` and `wifi_env` are erratic: high variance, no trend. They breach
  thresholds intermittently, which is exactly what produces false forecasts if the
  trend fit is not checked for goodness.

That last case is the reason `ScanConfig.min_trend_r2` exists. Without it a noisy
modem generates a confident straight line through nothing.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Literal, Sequence

Technology = Literal["HFC", "PON"]
Cause = Literal["stable", "cpe_state", "config_drift", "firmware", "wifi_env",
                "drop", "tap_or_odp", "plant"]

# Which KPI each cause moves, and in which direction. A cause that degraded every
# KPI at once would make classification trivial and unrealistic.
CAUSE_SIGNATURE: dict[Cause, dict[str, tuple[str, float]]] = {
    "stable":       {},
    "cpe_state":    {"t3_timeouts_per_day": ("erratic", 6.0),
                     "dying_gasp_per_day": ("erratic", 1.2)},
    "config_drift": {"us_tx_dbmv": ("step", 6.0), "ont_tx_dbm": ("step", 2.0)},
    "firmware":     {"ds_mer_db": ("step", -4.0), "ber": ("step", 4e-9)},
    "wifi_env":     {"t3_timeouts_per_day": ("erratic", 3.0)},
    # Trend magnitudes are per DAY. They must clear the measurement noise in
    # BASELINE or a degrading modem is indistinguishable from a healthy one: at
    # -0.05 dB/day against sigma 0.7, fourteen days of drift is buried.
    "drop":         {"us_tx_dbmv": ("trend", 0.34), "ds_mer_db": ("trend", -0.19),
                     "ont_rx_dbm": ("trend", -0.17)},
    "tap_or_odp":   {"ds_rx_dbmv": ("trend", -0.24), "ds_mer_db": ("trend", -0.16),
                     "ont_rx_dbm": ("trend", -0.21),
                     "uncorrectable_ratio": ("trend", 6.5e-6)},
    "plant":        {"ds_rx_dbmv": ("trend", -0.31), "ds_mer_db": ("trend", -0.26),
                     "ont_rx_dbm": ("trend", -0.29)},
}

# Share of the population by cause. Most modems are fine.
CAUSE_MIX: dict[Cause, float] = {
    "stable": 0.9380, "cpe_state": 0.0180, "config_drift": 0.0130,
    "firmware": 0.0080, "wifi_env": 0.0090, "drop": 0.0075,
    "tap_or_odp": 0.0045, "plant": 0.0020,
}

# When a reboot or reprovision only masks the problem, how many days until the
# modem degrades again. This is what produces genuine repeat offenders, which the
# operator selected as a notification trigger.
#
# config_drift is permanent: a corrected configuration stays corrected. The others
# recur because the reboot cleared a symptom, not a cause.
RELAPSE_AFTER_DAYS: dict[str, int | None] = {
    "config_drift": None, "firmware": 6, "cpe_state": 9, "wifi_env": 4,
    "drop": 2, "tap_or_odp": 2, "plant": 2, "stable": None,
}

HFC_KPIS = ("ds_rx_dbmv", "us_tx_dbmv", "ds_mer_db", "uncorrectable_ratio",
            "t3_timeouts_per_day")
PON_KPIS = ("ont_rx_dbm", "ont_tx_dbm", "ber", "dying_gasp_per_day")

BASELINE: dict[str, tuple[float, float]] = {   # (target, noise sigma)
    "ds_rx_dbmv": (0.5, 0.9), "us_tx_dbmv": (44.0, 1.1), "ds_mer_db": (38.5, 0.7),
    "uncorrectable_ratio": (2e-8, 1.5e-8), "t3_timeouts_per_day": (0.3, 0.5),
    "ont_rx_dbm": (-19.5, 0.7), "ont_tx_dbm": (2.6, 0.35),
    "ber": (1e-11, 8e-12), "dying_gasp_per_day": (0.05, 0.2),
}


@dataclass(frozen=True, slots=True)
class ModemSeries:
    modem_id: str
    site_id: str
    technology: Technology
    cause: Cause
    kpis: dict[str, tuple[float, ...]]     # oldest first, one sample per day

    def latest(self, kpi: str) -> float:
        return self.kpis[kpi][-1]

    @property
    def days(self) -> int:
        return len(next(iter(self.kpis.values()))) if self.kpis else 0


def _stable_rng(*parts: object) -> random.Random:
    """Per-modem RNG derived from a hash, so one modem's series never depends on
    how many others were generated before it."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _pick_cause(rng: random.Random) -> Cause:
    roll, acc = rng.random(), 0.0
    for cause, share in CAUSE_MIX.items():
        acc += share
        if roll <= acc:
            return cause
    return "stable"


def onset_day(modem_id: str, seed: int, *, horizon_days: int = 60) -> int:
    """The day this modem's degradation begins.

    Without a per-modem onset, every degrading modem is already degrading on day
    one: the first scan flags all of them and every later scan finds nothing. A
    real network has a steady state because new modems start failing every day, and
    a daily scan is only worth running if that is true.
    """
    return _stable_rng(seed, modem_id, "onset").randrange(0, max(1, horizon_days))


def series_for(modem_id: str, site_id: str, technology: Technology, *,
               days: int, seed: int, cause: Cause | None = None,
               day_index: int = 0, onset_horizon_days: int = 60) -> ModemSeries:
    """Telemetry for one modem as observed on day `day_index`.

    `day_index` advances the simulation: a modem whose onset has not arrived reads
    as healthy, and one well past onset may already have breached.
    """
    rng = _stable_rng(seed, modem_id)
    chosen: Cause = cause or _pick_cause(rng)

    # Before onset the modem is simply healthy, whatever its eventual cause.
    if cause is None and chosen != "stable":
        begins = onset_day(modem_id, seed, horizon_days=onset_horizon_days)
        if day_index < begins:
            chosen = "stable"
        else:
            # progress is how long it has been degrading, in days since onset
            rng = _stable_rng(seed, modem_id, "prog")
            elapsed_days = day_index - begins
    signature = CAUSE_SIGNATURE[chosen]
    kpi_names = HFC_KPIS if technology == "HFC" else PON_KPIS

    # Where in its life the degradation is. A population all at day zero would
    # produce no proactive tickets at all.
    progress = rng.random()
    if cause is None and chosen != "stable":
        # blend the stochastic placement with the deterministic day count
        progress = min(1.0, progress * 0.35 + elapsed_days / 26.0)
    step_day = int(days * rng.uniform(0.25, 0.8))

    kpis: dict[str, tuple[float, ...]] = {}
    for kpi in kpi_names:
        target, sigma = BASELINE[kpi]
        mode, magnitude = signature.get(kpi, (None, 0.0))
        samples = []
        for day in range(days):
            value = rng.gauss(target, sigma)
            if mode == "trend":
                # `progress` places the modem somewhere along its decline, so the
                # population contains modems already past an alarm threshold
                # (proactive tickets) as well as ones heading for one (forecast).
                elapsed = progress * days * 2.6 + day
                value += magnitude * elapsed
            elif mode == "step" and day >= step_day:
                value += magnitude
            elif mode == "erratic":
                value += abs(rng.gauss(0, magnitude)) if rng.random() < 0.35 else 0.0
            if kpi in ("uncorrectable_ratio", "ber", "t3_timeouts_per_day",
                       "dying_gasp_per_day"):
                value = max(0.0, value)
            samples.append(round(value, 10))
        kpis[kpi] = tuple(samples)

    return ModemSeries(modem_id, site_id, technology, chosen, kpis)


def linear_trend(values: Sequence[float]) -> tuple[float, float, float]:
    """Least-squares slope per day, intercept, and r-squared.

    r-squared is returned because it is the guard against a confident line drawn
    through noise. A modem with an erratic cause can produce a steep slope and an
    r-squared near zero; without the check it becomes a forecast ticket.
    """
    n = len(values)
    if n < 2:
        return 0.0, (values[0] if values else 0.0), 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    if sxx == 0:
        return 0.0, mean_y, 0.0
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in values)
    if ss_tot == 0:
        return slope, intercept, 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, values))
    return slope, intercept, max(0.0, 1.0 - ss_res / ss_tot)


def days_to_threshold(values: Sequence[float], threshold: float, *,
                      direction: Literal["falling", "rising"]) -> float | None:
    """Days until the fitted trend reaches `threshold`.

    Returns None when the trend moves away from the threshold, is flat, or has
    already crossed it — the last case is a proactive ticket, not a forecast.
    """
    if not values:
        return None
    slope, intercept, _ = linear_trend(values)
    current = slope * (len(values) - 1) + intercept
    if direction == "falling":
        if current <= threshold:
            return None
        if slope >= -1e-12:
            return None
    else:
        if current >= threshold:
            return None
        if slope <= 1e-12:
            return None
    days = (threshold - current) / slope
    return days if days > 0 and math.isfinite(days) else None
