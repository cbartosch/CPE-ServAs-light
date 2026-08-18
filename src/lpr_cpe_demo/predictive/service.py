"""The scheduled service: one daily run, end to end.

A separate branch of the stack, as specified. It scans, processes, and hands the
gated tickets to the main flow. It keeps its own flag history across runs, which is
what makes repeat-offender detection possible.

Deliberately not a scheduler. A cron entry, a Kubernetes CronJob or a compose
service with a sleep loop can all call `run_once`; embedding a scheduler here would
make the service untestable and hide the timing in code rather than in
configuration.
"""

from __future__ import annotations

import json
import pathlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from .config import DEFAULT_REMEDIATION, DEFAULT_SCAN, RemediationConfig, ScanConfig
from .handoff import IncidentSeed, seed_from
from .pipeline import Outcome, process
from .scanner import PredictiveTicket, ScanResult, scan
from .signals import RELAPSE_AFTER_DAYS, ModemSeries, series_for


@dataclass(slots=True)
class FlagHistory:
    """Which modems were flagged when, so repeat offenders are detectable.

    Persisted as JSON because this branch has no database of its own and must
    survive a container restart: repeat-offender status is a notification trigger,
    so losing it silently changes who gets told.
    """

    path: pathlib.Path | None = None
    flags: dict[str, list[str]] = field(default_factory=dict)
    # Modem id to the class of a ticket still open for it. Persisted with the
    # flags because a restart that forgot the open tickets would reopen every one
    # of them on the next run.
    open_tickets: dict[str, str] = field(default_factory=dict)

    def load(self) -> "FlagHistory":
        if self.path and self.path.exists():
            try:
                blob = json.loads(self.path.read_text())
                self.flags = blob.get("closed_flags", {})
                self.open_tickets = blob.get("open_tickets", {})
            except Exception:
                # a corrupt file must not stop the scan
                self.flags, self.open_tickets = {}, {}
        return self

    def as_datetimes(self) -> dict[str, list[datetime]]:
        out: dict[str, list[datetime]] = {}
        for modem, stamps in self.flags.items():
            parsed = []
            for stamp in stamps:
                try:
                    parsed.append(datetime.fromisoformat(stamp))
                except ValueError:
                    continue
                    
            out[modem] = parsed
        return out

    def record(self, tickets: Iterable[PredictiveTicket], *,
               closed: Iterable[str] = (), keep_days: int = 90) -> None:
        """Record the run. Only CLOSED tickets enter the repeat-offender history."""
        closed_ids = set(closed)
        for ticket in tickets:
            if ticket.ticket_id in closed_ids:
                self.flags.setdefault(ticket.modem_id, []).append(
                    ticket.opened_at.isoformat())
                self.open_tickets.pop(ticket.modem_id, None)
            else:
                self.open_tickets[ticket.modem_id] = ticket.ticket_class
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        for modem, stamps in list(self.flags.items()):
            kept = []
            for stamp in stamps:
                try:
                    if datetime.fromisoformat(stamp) >= cutoff:
                        kept.append(stamp)
                except ValueError:
                    continue
            if kept:
                self.flags[modem] = kept
            else:
                del self.flags[modem]

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"closed_flags": self.flags, "open_tickets": self.open_tickets}, indent=1))


def _parse_times(stamps: Iterable[str]) -> list[datetime]:
    out = []
    for stamp in stamps:
        try:
            out.append(datetime.fromisoformat(stamp))
        except ValueError:
            continue
    return out


@dataclass(slots=True)
class RunReport:
    run_id: str
    ran_at: datetime
    scan: ScanResult
    outcomes: list[Outcome] = field(default_factory=list)
    seeds: list[IncidentSeed] = field(default_factory=list)

    @property
    def auto_closed(self) -> int:
        return sum(1 for o in self.outcomes if o.verdict == "allowed")

    @property
    def gated(self) -> int:
        return sum(1 for o in self.outcomes if o.verdict == "requires_approval")

    @property
    def truck_rolls(self) -> int:
        return sum(1 for o in self.outcomes if o.needs_truck_roll)

    @property
    def notifications(self) -> int:
        return sum(1 for o in self.outcomes if o.notification_required)

    @property
    def service_interruption_minutes(self) -> int:
        return sum(o.service_interruption_minutes for o in self.outcomes)

    def summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id, "ran_at": self.ran_at.isoformat(),
            "scanned": self.scan.scanned, "healthy": self.scan.healthy,
            "tickets": len(self.scan.tickets),
            "suppressed_as_duplicate": self.scan.suppressed_as_duplicate,
            "flag_rate": self.scan.flag_rate,
            "by_class": self.scan.by_class,
            "suppressed_by_cap": self.scan.suppressed_by_cap,
            "auto_closed": self.auto_closed, "gated": self.gated,
            "auto_close_rate": (round(self.auto_closed / len(self.outcomes), 4)
                                if self.outcomes else 0.0),
            "truck_rolls": self.truck_rolls,
            "notifications": self.notifications,
            "handed_to_main_flow": len(self.seeds),
            "service_interruption_minutes": self.service_interruption_minutes,
        }


def synthetic_population(count: int, *, seed: int, sites: Sequence[str],
                         days: int, day_index: int = 0) -> list[ModemSeries]:
    """The population as observed on `day_index` of the simulation."""
    rng = random.Random(seed)
    out = []
    for index in range(count):
        site = sites[index % len(sites)]
        technology = "PON" if rng.random() < 0.35 else "HFC"
        out.append(series_for(f"CM-{index:07d}", site, technology, days=days,
                              seed=seed, day_index=day_index))
    return out


def run_once(*, run_id: str | None = None, ran_at: datetime | None = None,
             population: Iterable[ModemSeries] | None = None,
             sites: Sequence[str] | None = None,
             history: FlagHistory | None = None,
             scan_config: ScanConfig = DEFAULT_SCAN,
             remediation: RemediationConfig = DEFAULT_REMEDIATION,
             rng_seed: int = 20260818, day_index: int = 0) -> RunReport:
    """One daily cycle: scan, auto-remediate, gate, hand over."""
    moment = ran_at or datetime.now(timezone.utc).replace(
        hour=scan_config.scan_hour_local, minute=0, second=0, microsecond=0)
    identifier = run_id or moment.strftime("%Y%m%d")
    flag_history = history or FlagHistory()

    if population is None:
        from ..geography import sites_in_cpe_footprint
        site_ids = list(sites) if sites else [s.site_id
                                             for s in sites_in_cpe_footprint()]
        population = synthetic_population(scan_config.population, seed=rng_seed,
                                          sites=site_ids,
                                          days=scan_config.trend_window_days,
                                          day_index=day_index)

    pool = list(population)
    # A modem whose ticket was resolved is no longer degraded -- until it relapses.
    # A reboot that cleared a symptom rather than a cause buys days, not a fix, and
    # the modem coming back is exactly the repeat offender the operator wants
    # notified. Without both halves the simulation is wrong in one direction or the
    # other: re-flagging forever, or a network that heals permanently by day three.
    recovered_on = {modem: max(_parse_times(stamps))
                    for modem, stamps in flag_history.flags.items()
                    if _parse_times(stamps)}
    healed = []
    for series in pool:
        closed_at = recovered_on.get(series.modem_id)
        if closed_at is None:
            healed.append(series)
            continue
        relapse_after = RELAPSE_AFTER_DAYS.get(series.cause)
        days_since = (moment - closed_at).total_seconds() / 86400.0
        if relapse_after is not None and days_since >= relapse_after:
            healed.append(series)          # relapsed: the original cause is back
        else:
            healed.append(series_for(series.modem_id, series.site_id,
                                     series.technology,
                                     days=scan_config.trend_window_days,
                                     seed=rng_seed, cause="stable"))
    pool = healed

    result = scan(pool, run_id=identifier, ran_at=moment, config=scan_config,
                  previous_flags=flag_history.as_datetimes(),
                  open_tickets=dict(flag_history.open_tickets))

    rng = random.Random(rng_seed)
    report = RunReport(run_id=identifier, ran_at=moment, scan=result)
    for ticket in result.tickets:
        rolls = [rng.random() for _ in range(remediation.max_auto_attempts)]
        outcome = process(ticket, hour=moment.hour, rolls=rolls,
                          scan_config=scan_config, remediation=remediation)
        report.outcomes.append(outcome)
        if outcome.verdict == "requires_approval":
            report.seeds.append(seed_from(ticket, outcome))

    closed = [o.ticket_id for o in report.outcomes if o.verdict == "allowed"]
    flag_history.record(result.tickets, closed=closed)
    flag_history.save()
    return report
