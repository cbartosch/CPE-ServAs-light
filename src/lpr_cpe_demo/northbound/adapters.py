"""Convert northbound messages into the internal model.

A northbound feed is untrusted input. It arrives with fields missing, numbers as
strings, enumerations the sender invented, timestamps without a zone, and counters
where a rate was expected. Every adapter here validates before it converts and
raises `AdapterError` with the offending field rather than producing a plausible
wrong value.

Three conversions are where integrations actually go wrong, so each is explicit:

**Scaling.** DOCSIS MIB power and MER are in tenths; TR-181 optical power is in
hundredths. Read as plain units, a downstream Rx of `-118` becomes -118 dBmV — a
modem reported dead when it is at -11.8 dBmV and in service.

**Counters, not rates.** `docsIfSigQUncorrectables` is cumulative since boot. A
single sample cannot yield a rate, so `uncorrectable_rate` needs two samples and
returns `None` from one. Treating the raw counter as a rate flags every modem that
has been up for a year.

**Counter wrap and reboot.** If the later counter is lower than the earlier one,
the device rebooted or the counter wrapped. The delta is not negative; it is
unknown, and the adapter says so instead of returning a negative rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import contract_for


class AdapterError(ValueError):
    """A message could not be converted. Carries the field that failed."""


def _require(payload: Mapping[str, Any], path: str, system: str) -> Any:
    node: Any = payload
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise AdapterError(f"{system}: missing required field {path!r}")
        node = node[part]
    return node


def _number(value: Any, path: str, system: str) -> float:
    """Accept the string form these systems actually send."""
    if isinstance(value, bool):
        raise AdapterError(f"{system}: {path!r} is a boolean, expected a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise AdapterError(f"{system}: {path!r}={value!r} is not numeric") from exc
    raise AdapterError(f"{system}: {path!r} has type {type(value).__name__}")


def _timestamp(value: Any, path: str, system: str) -> datetime:
    if not isinstance(value, str):
        raise AdapterError(f"{system}: {path!r} is not a timestamp string")
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AdapterError(f"{system}: {path!r}={value!r} is not ISO 8601") from exc
    if parsed.tzinfo is None:
        # A naive timestamp from a northbound feed is ambiguous. Assuming local
        # time silently shifts every measurement by the offset.
        raise AdapterError(f"{system}: {path!r} has no timezone; refusing to guess")
    return parsed.astimezone(timezone.utc)


# ------------------------------------------------------------------ scaling
DOCSIS_TENTHS = ("docsIfDownChannelPower", "docsIf3CmStatusUsTxPower",
                 "docsIf3SignalQualityExtRxMER")
TR181_HUNDREDTHS = ("Device.Optical.Interface.1.CurrentDownstreamRxPower",
                    "Device.Optical.Interface.1.CurrentUpstreamTxPower")
COUNTERS = ("docsIfSigQUncorrectables", "docsIf3CmtsCmUsStatusT3Timeouts")

# Wire name to the internal KPI name used by the predictive scanner.
CPE_KPI_MAP = {
    "docsIfDownChannelPower": "ds_rx_dbmv",
    "docsIf3CmStatusUsTxPower": "us_tx_dbmv",
    "docsIf3SignalQualityExtRxMER": "ds_mer_db",
    "Device.Optical.Interface.1.CurrentDownstreamRxPower": "ont_rx_dbm",
    "Device.Optical.Interface.1.CurrentUpstreamTxPower": "ont_tx_dbm",
}


@dataclass(frozen=True, slots=True)
class CpeSample:
    modem_id: str
    technology: str
    firmware: str
    uptime_seconds: int
    observed_at: datetime
    kpis: dict[str, float]
    counters: dict[str, int]
    rejected: tuple[str, ...] = ()

    @property
    def recently_rebooted(self) -> bool:
        return self.uptime_seconds < 3600


def parse_cpe_usp(message: Mapping[str, Any]) -> CpeSample:
    """TR-369 USP Notify carrying TR-181 and DOCSIS parameters."""
    system = "CPE"
    params = _require(message, "body.request.notify.event.params", system)
    if not isinstance(params, Mapping):
        raise AdapterError(f"{system}: params is not an object")

    serial = params.get("Device.DeviceInfo.SerialNumber")
    if not serial:
        raise AdapterError(f"{system}: Device.DeviceInfo.SerialNumber is required; "
                           f"nothing can be keyed without it")

    product = str(params.get("Device.DeviceInfo.ProductClass", ""))
    technology = "PON" if "PON" in product.upper() or any(
        p in params for p in TR181_HUNDREDTHS) else "HFC"

    kpis: dict[str, float] = {}
    counters: dict[str, int] = {}
    rejected: list[str] = []

    for wire_name, raw in params.items():
        if wire_name in DOCSIS_TENTHS:
            kpis[CPE_KPI_MAP[wire_name]] = round(
                _number(raw, wire_name, system) / 10.0, 3)
        elif wire_name in TR181_HUNDREDTHS:
            kpis[CPE_KPI_MAP[wire_name]] = round(
                _number(raw, wire_name, system) / 100.0, 3)
        elif wire_name in COUNTERS:
            counters[wire_name] = int(_number(raw, wire_name, system))
        elif wire_name.startswith("docsIf") or wire_name.startswith("Device."):
            continue                       # known but not consumed
        else:
            rejected.append(wire_name)     # unknown; recorded, never guessed at

    collector = message.get("_collector") or {}
    observed = _timestamp(collector.get("receivedAt", ""), "_collector.receivedAt",
                          system) if collector.get("receivedAt") else \
        datetime.now(timezone.utc)

    return CpeSample(
        modem_id=str(serial), technology=technology,
        firmware=str(params.get("Device.DeviceInfo.SoftwareVersion", "")),
        uptime_seconds=int(_number(params.get("Device.DeviceInfo.UpTime", 0),
                                   "Device.DeviceInfo.UpTime", system)),
        observed_at=observed, kpis=kpis, counters=counters,
        rejected=tuple(rejected))


def counter_rate(earlier: CpeSample, later: CpeSample, counter: str) -> float | None:
    """Events per day between two samples, or None when it cannot be known.

    Returns None on a single sample, on a zero interval, and on a counter that
    went backwards, which means a reboot or a wrap rather than a negative rate.
    """
    if counter not in earlier.counters or counter not in later.counters:
        return None
    seconds = (later.observed_at - earlier.observed_at).total_seconds()
    if seconds <= 0:
        return None
    delta = later.counters[counter] - earlier.counters[counter]
    if delta < 0:
        return None                        # reboot or wrap; unknown, not negative
    return round(delta / seconds * 86400.0, 4)


# --------------------------------------------------------------------- NXT
@dataclass(frozen=True, slots=True)
class NxtSnapshot:
    snapshot_id: str
    taken_at: datetime
    subscriber_id: str
    service_id: str
    technology: str
    service_state: str
    provisioning_state: str
    delimiter_id: str | None
    delimiter_type: str | None
    households_behind_delimiter: int | None
    node_id: str | None
    events: tuple[dict[str, Any], ...]
    open_tickets: tuple[str, ...]

    @property
    def degraded(self) -> bool:
        return self.service_state in {"degraded", "down"}


NXT_SERVICE_STATES = {"active", "degraded", "down", "suspended"}
NXT_PROVISIONING_STATES = {"in_sync", "drifted", "failed"}


def parse_nxt_snapshot(message: Mapping[str, Any]) -> NxtSnapshot:
    """MODELLED SHAPE. Field names are placeholders, not read from a spec.

    The validation is real even though the schema is a guess: an unexpected
    enumeration value is rejected rather than passed through, because a silently
    accepted `serviceState` of `"DEGRADED "` with a trailing space will match
    nothing downstream and look like a healthy service.
    """
    system = "NXT"
    state = str(_require(message, "serviceState", system)).strip().lower()
    if state not in NXT_SERVICE_STATES:
        raise AdapterError(f"{system}: serviceState={state!r} is not one of "
                           f"{sorted(NXT_SERVICE_STATES)}")
    provisioning = str(_require(message, "provisioningState", system)).strip().lower()
    if provisioning not in NXT_PROVISIONING_STATES:
        raise AdapterError(f"{system}: provisioningState={provisioning!r} is not "
                           f"one of {sorted(NXT_PROVISIONING_STATES)}")

    topology = message.get("topology") or {}
    households = topology.get("householdsBehindDelimiter")
    return NxtSnapshot(
        snapshot_id=str(_require(message, "snapshotId", system)),
        taken_at=_timestamp(_require(message, "takenAt", system), "takenAt", system),
        subscriber_id=str(_require(message, "subscriberId", system)),
        service_id=str(_require(message, "serviceId", system)),
        technology=str(_require(message, "accessTechnology", system)).upper(),
        service_state=state, provisioning_state=provisioning,
        delimiter_id=topology.get("delimiterId"),
        delimiter_type=topology.get("delimiterType"),
        households_behind_delimiter=(int(households) if households is not None
                                     else None),
        node_id=topology.get("nodeId"),
        events=tuple(message.get("recentEvents") or []),
        open_tickets=tuple(message.get("openTickets") or []))


# --------------------------------------------------------------------- WFM
TMF697_STATES = {"acknowledged", "inProgress", "completed", "cancelled", "failed",
                 "held", "rejected", "pending"}


@dataclass(frozen=True, slots=True)
class WorkOrder:
    work_order_id: str
    state: str
    crew_type: str | None
    dispatch_base: str | None
    delimiter_id: str | None
    appointment_start: datetime | None
    characteristics: dict[str, str] = field(default_factory=dict)
    resolution_code: str | None = None
    no_fault_found: bool | None = None
    on_site_minutes: int | None = None

    @property
    def closed(self) -> bool:
        return self.state in {"completed", "cancelled", "failed", "rejected"}


def _characteristics(items: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if isinstance(item, Mapping) and "name" in item:
            out[str(item["name"])] = str(item.get("value", ""))
    return out


def parse_wfm_work_order(message: Mapping[str, Any]) -> WorkOrder:
    """TMF697 Work Order, or a WorkOrderStateChangeEvent carrying one."""
    system = "WFM"
    body = message
    if message.get("eventType") == "WorkOrderStateChangeEvent":
        body = _require(message, "event.workOrder", system)

    state = str(_require(body, "state", system))
    if state not in TMF697_STATES:
        raise AdapterError(f"{system}: state={state!r} is not a TMF697 state")

    chars = _characteristics(body.get("characteristic"))
    appointment = None
    start = (body.get("appointment") or {}).get("validFor", {}).get("startDateTime")
    if start:
        appointment = _timestamp(start, "appointment.validFor.startDateTime", system)

    nff = chars.get("noFaultFound")
    minutes = chars.get("onSiteMinutes")
    return WorkOrder(
        work_order_id=str(_require(body, "id", system)), state=state,
        crew_type=chars.get("crewType"), dispatch_base=chars.get("dispatchBase"),
        delimiter_id=chars.get("delimiterId"), appointment_start=appointment,
        characteristics=chars, resolution_code=chars.get("resolutionCode"),
        no_fault_found=None if nff is None else nff.strip().lower() == "true",
        on_site_minutes=int(minutes) if minutes and minutes.isdigit() else None)


# ------------------------------------------------------------------ jTrack
TMF621_STATUSES = {"acknowledged", "inProgress", "pending", "held", "resolved",
                   "closed", "rejected", "cancelled"}
TMF621_SEVERITIES = {"critical", "major", "minor", "warning"}


@dataclass(frozen=True, slots=True)
class TroubleTicket:
    ticket_id: str
    status: str
    severity: str
    description: str
    affected_service: str | None
    suspect_resource: str | None
    predictive_ticket_id: str | None
    created_at: datetime | None
    notes: tuple[str, ...] = ()

    @property
    def open(self) -> bool:
        return self.status not in {"resolved", "closed", "rejected", "cancelled"}


def parse_jtrack_ticket(message: Mapping[str, Any]) -> TroubleTicket:
    """TMF621 Trouble Ticket, or a TroubleTicketStatusChangeEvent carrying one."""
    system = "jTrack"
    body = message
    if message.get("eventType") == "TroubleTicketStatusChangeEvent":
        body = _require(message, "event.troubleTicket", system)

    status = str(_require(body, "status", system))
    if status not in TMF621_STATUSES:
        raise AdapterError(f"{system}: status={status!r} is not a TMF621 status")
    severity = str(body.get("severity", "minor"))
    if severity not in TMF621_SEVERITIES:
        raise AdapterError(f"{system}: severity={severity!r} is not a TMF621 "
                           f"severity")

    related = {str(e.get("role")): str(e.get("id"))
               for e in body.get("relatedEntity") or [] if isinstance(e, Mapping)}
    external = None
    for entry in body.get("externalIdentifier") or []:
        if isinstance(entry, Mapping) and \
                entry.get("externalIdentifierType") == "predictiveTicket":
            external = str(entry.get("id"))

    created = body.get("creationDate")
    return TroubleTicket(
        ticket_id=str(_require(body, "id", system)), status=status,
        severity=severity, description=str(body.get("description", "")),
        affected_service=related.get("affectedService"),
        suspect_resource=related.get("suspectResource"),
        predictive_ticket_id=external,
        created_at=_timestamp(created, "creationDate", system) if created else None,
        notes=tuple(str(n.get("text", "")) for n in body.get("note") or []
                    if isinstance(n, Mapping)))


ADAPTERS = {"CPE": parse_cpe_usp, "NXT": parse_nxt_snapshot,
            "WFM": parse_wfm_work_order, "jTrack": parse_jtrack_ticket}


def parse(system: str, message: Mapping[str, Any]) -> Any:
    contract_for(system)                   # raises KeyError on an unknown system
    return ADAPTERS[contract_for(system).system](message)
