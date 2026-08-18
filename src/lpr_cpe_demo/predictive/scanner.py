"""The daily scan: classify modems, raise tickets, deduplicate.

Two ticket classes, as specified:

`proactive`  a KPI has ALREADY crossed an alarm threshold and no customer has
             called. Urgency is high; the SLA is 24 hours.
`forecast`   a fitted trend reaches an alarm threshold inside the horizon, and the
             fit explains enough variance to be worth acting on. The modem still
             works. SLA is 120 hours.

A modem that qualifies for both is `proactive`: it has already broken, so
forecasting when it will break is not the useful statement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal, Sequence

from .config import (HFC_THRESHOLDS, PON_THRESHOLDS, DEFAULT_SCAN, ScanConfig,
                     TicketClass)
from .signals import (HFC_KPIS, PON_KPIS, ModemSeries, days_to_threshold,
                      linear_trend)

Direction = Literal["falling", "rising"]

# Which alarm bound each KPI can breach, and in which direction.
ALARM_BOUNDS: dict[str, tuple[str, Direction]] = {
    "ds_rx_dbmv": ("alarm_low", "falling"),
    "us_tx_dbmv": ("alarm_high", "rising"),
    "ds_mer_db": ("alarm_low", "falling"),
    "uncorrectable_ratio": ("alarm_high", "rising"),
    "t3_timeouts_per_day": ("alarm_high", "rising"),
    "ont_rx_dbm": ("alarm_low", "falling"),
    "ont_tx_dbm": ("alarm_low", "falling"),
    "ber": ("alarm_high", "rising"),
    "dying_gasp_per_day": ("alarm_high", "rising"),
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass(frozen=True, slots=True)
class Finding:
    kpi: str
    value: float
    threshold: float
    direction: Direction
    breached_now: bool
    days_to_breach: float | None
    slope_per_day: float
    r_squared: float

    @property
    def margin(self) -> float:
        """How far past the threshold, or how far short of it."""
        return (self.threshold - self.value if self.direction == "falling"
                else self.value - self.threshold)


@dataclass(frozen=True, slots=True)
class PredictiveTicket:
    ticket_id: str
    modem_id: str
    site_id: str
    technology: str
    ticket_class: TicketClass
    severity: str
    opened_at: datetime
    sla_due_at: datetime
    findings: tuple[Finding, ...]
    suspected_cause: str
    repeat_offender: bool
    previous_flags: int
    scan_run_id: str

    @property
    def headline(self) -> Finding:
        """The finding that drove the ticket: worst breach, or soonest breach."""
        breached = [f for f in self.findings if f.breached_now]
        if breached:
            return max(breached, key=lambda f: f.margin)
        with_eta = [f for f in self.findings if f.days_to_breach is not None]
        return min(with_eta, key=lambda f: f.days_to_breach) if with_eta \
            else self.findings[0]

    @property
    def dedup_key(self) -> str:
        return f"{self.modem_id}|{self.ticket_class}"


@dataclass(slots=True)
class ScanResult:
    run_id: str
    ran_at: datetime
    scanned: int
    tickets: list[PredictiveTicket] = field(default_factory=list)
    suppressed_by_cap: int = 0
    suppressed_as_duplicate: int = 0
    healthy: int = 0

    @property
    def by_class(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for ticket in self.tickets:
            out[ticket.ticket_class] = out.get(ticket.ticket_class, 0) + 1
        return out

    @property
    def flag_rate(self) -> float:
        return round(len(self.tickets) / self.scanned, 5) if self.scanned else 0.0


def _thresholds(technology: str) -> dict[str, dict[str, float]]:
    return HFC_THRESHOLDS if technology == "HFC" else PON_THRESHOLDS


def evaluate(series: ModemSeries, config: ScanConfig = DEFAULT_SCAN) -> list[Finding]:
    """Every KPI that has breached an alarm bound or is trending into one."""
    table = _thresholds(series.technology)
    findings: list[Finding] = []
    for kpi in (HFC_KPIS if series.technology == "HFC" else PON_KPIS):
        bound_name, direction = ALARM_BOUNDS[kpi]
        limits = table.get(kpi, {})
        if bound_name not in limits:
            continue
        threshold = limits[bound_name]
        values = series.kpis[kpi]
        current = values[-1]
        breached = current <= threshold if direction == "falling" else current >= threshold

        slope, _, r2 = linear_trend(values)
        eta = None
        if not breached and len(values) >= config.min_samples_for_trend \
                and r2 >= config.min_trend_r2:
            eta = days_to_threshold(values, threshold, direction=direction)
            if eta is not None and eta > config.forecast_horizon_days:
                eta = None

        if breached or eta is not None:
            findings.append(Finding(kpi, round(current, 10), threshold, direction,
                                    breached, None if eta is None else round(eta, 2),
                                    round(slope, 6), round(r2, 4)))
    return findings


def _severity(ticket_class: TicketClass, findings: Sequence[Finding]) -> str:
    if ticket_class == "proactive":
        return "critical" if len(findings) >= 2 else "high"
    soonest = min((f.days_to_breach for f in findings
                   if f.days_to_breach is not None), default=999.0)
    if soonest <= 3:
        return "high"
    return "medium" if soonest <= 7 else "low"


def scan(population: Iterable[ModemSeries], *, run_id: str, ran_at: datetime,
         config: ScanConfig = DEFAULT_SCAN,
         previous_flags: dict[str, list[datetime]] | None = None,
         open_tickets: dict[str, str] | None = None) -> ScanResult:
    """One daily run.

    `previous_flags` holds the times a modem was flagged and then CLOSED. Only
    closed flags count towards repeat-offender status: a modem still degraded
    while its ticket is open is the same incident, not a repeat. Counting it as a
    repeat made the notification trigger fire on the entire population by day two
    and auto-close rate fell to zero.

    `open_tickets` maps modem id to the class of a ticket already open for it. A
    duplicate is suppressed rather than raised, because a scan that reopens the
    same finding every night generates work, not information.
    """
    history = previous_flags or {}
    already_open = open_tickets or {}
    result = ScanResult(run_id=run_id, ran_at=ran_at, scanned=0)
    candidates: list[PredictiveTicket] = []

    for index, series in enumerate(population):
        result.scanned += 1
        findings = evaluate(series, config)
        if not findings:
            result.healthy += 1
            continue

        # Already broken beats predicted to break.
        breached = [f for f in findings if f.breached_now]
        ticket_class: TicketClass = "proactive" if breached else "forecast"

        # A ticket already open for this modem suppresses a duplicate. A proactive
        # finding does escalate an open forecast ticket, because the thing it was
        # predicting has now happened.
        open_class = already_open.get(series.modem_id)
        if open_class is not None and not (open_class == "forecast"
                                           and ticket_class == "proactive"):
            result.suppressed_as_duplicate += 1
            continue

        window_start = ran_at - timedelta(days=config.repeat_window_days)
        prior = [t for t in history.get(series.modem_id, []) if t >= window_start]
        severity = _severity(ticket_class, findings)

        candidates.append(PredictiveTicket(
            ticket_id=f"PRD-{run_id}-{index + 1:05d}",
            modem_id=series.modem_id, site_id=series.site_id,
            technology=series.technology, ticket_class=ticket_class,
            severity=severity, opened_at=ran_at,
            sla_due_at=ran_at + timedelta(hours=config.sla_hours[ticket_class]),
            findings=tuple(findings), suspected_cause=series.cause,
            repeat_offender=bool(prior), previous_flags=len(prior),
            scan_run_id=run_id))

    # Cap the run. Worst first, so the cap drops the least urgent rather than an
    # arbitrary tail.
    candidates.sort(key=lambda t: (SEVERITY_ORDER[t.severity],
                                   0 if t.ticket_class == "proactive" else 1,
                                   t.ticket_id))
    if len(candidates) > config.max_tickets_per_run:
        result.suppressed_by_cap = len(candidates) - config.max_tickets_per_run
        candidates = candidates[:config.max_tickets_per_run]
    result.tickets = candidates
    return result
