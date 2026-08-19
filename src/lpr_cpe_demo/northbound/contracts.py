"""Field-level contracts for each northbound system.

Every field records where its name comes from. `STANDARD` means the name appears
in a published specification and can be checked against it; `MODELLED` means I
chose it because the real one is unknown.

This matters operationally. An integrator reading this file needs to know which
names to take to the vendor and which to take to the standard, and a mixed list
with no marking sends them to the wrong place for half of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Provenance = Literal["STANDARD", "MODELLED"]


@dataclass(frozen=True, slots=True)
class FieldSpec:
    path: str
    kind: str
    provenance: Provenance
    source: str
    note: str = ""
    required: bool = True


@dataclass(frozen=True, slots=True)
class SystemContract:
    system: str
    transport: str
    provenance: Provenance
    specification: str
    fields: tuple[FieldSpec, ...]

    @property
    def required_paths(self) -> tuple[str, ...]:
        return tuple(f.path for f in self.fields if f.required)


# --------------------------------------------------------------------- CPE
# TR-181 Device Data Model paths, carried on a TR-369 (USP) Notify. DOCSIS
# counters keep their CM-SP-CM-OSSI MIB object names because that is what a PNM
# collector emits and what an operator will recognise.
_TR181 = "Broadband Forum TR-181 Device Data Model"
_USP = "Broadband Forum TR-369 (USP)"
_DOCSIS = "CableLabs CM-SP-CM-OSSI DOCSIS MIB"

CPE_CONTRACT = SystemContract(
    system="CPE", transport="TR-369 USP Notify over MQTT or WebSocket",
    provenance="STANDARD", specification=f"{_TR181}, {_USP}, {_DOCSIS}",
    fields=(
        FieldSpec("Device.DeviceInfo.SerialNumber", "str", "STANDARD", _TR181,
                  "the modem identity everything else keys on"),
        FieldSpec("Device.DeviceInfo.SoftwareVersion", "str", "STANDARD", _TR181,
                  "firmware, needed to distinguish a firmware cause"),
        FieldSpec("Device.DeviceInfo.UpTime", "int", "STANDARD", _TR181,
                  "seconds; a low value after a high one is a reboot"),
        FieldSpec("Device.DeviceInfo.ProductClass", "str", "STANDARD", _TR181,
                  "distinguishes a modem from an ONT", required=False),
        # DOCSIS
        FieldSpec("docsIfDownChannelPower", "float", "STANDARD", _DOCSIS,
                  "downstream Rx in tenths of a dBmV on the wire",
                  required=False),
        FieldSpec("docsIf3CmStatusUsTxPower", "float", "STANDARD", _DOCSIS,
                  "upstream Tx in tenths of a dBmV", required=False),
        FieldSpec("docsIf3SignalQualityExtRxMER", "float", "STANDARD", _DOCSIS,
                  "MER in tenths of a dB", required=False),
        FieldSpec("docsIfSigQUncorrectables", "int", "STANDARD", _DOCSIS,
                  "cumulative counter, so a rate needs two samples",
                  required=False),
        FieldSpec("docsIf3CmtsCmUsStatusT3Timeouts", "int", "STANDARD", _DOCSIS,
                  "cumulative counter", required=False),
        # PON
        FieldSpec("Device.Optical.Interface.1.CurrentDownstreamRxPower", "float",
                  "STANDARD", _TR181, "ONT Rx, hundredths of a dBm",
                  required=False),
        FieldSpec("Device.Optical.Interface.1.CurrentUpstreamTxPower", "float",
                  "STANDARD", _TR181, "ONT Tx, hundredths of a dBm",
                  required=False),
        FieldSpec("Device.Optical.Interface.1.Status", "str", "STANDARD", _TR181,
                  "Up, Down, LowerLayerDown", required=False),
    ))

# --------------------------------------------------------------------- NXT
# INVENTED. The evidence refs in the existing scenarios are `nxt.snapshot`, which
# implies a point-in-time assurance view, so that is what this models. Nothing
# here was read from an NXT specification.
_NXT = "MODELLED, no specification available to me"

NXT_CONTRACT = SystemContract(
    system="NXT", transport="MODELLED: REST poll or Kafka topic",
    provenance="MODELLED", specification=_NXT,
    fields=(
        FieldSpec("snapshotId", "str", "MODELLED", _NXT),
        FieldSpec("takenAt", "str", "MODELLED", _NXT, "ISO 8601"),
        FieldSpec("subscriberId", "str", "MODELLED", _NXT),
        FieldSpec("serviceId", "str", "MODELLED", _NXT),
        FieldSpec("accessTechnology", "str", "MODELLED", _NXT, "HFC or PON"),
        FieldSpec("serviceState", "str", "MODELLED", _NXT,
                  "modelled enum: active, degraded, down, suspended"),
        FieldSpec("provisioningState", "str", "MODELLED", _NXT,
                  "modelled enum: in_sync, drifted, failed"),
        FieldSpec("topology.nodeId", "str", "MODELLED", _NXT, required=False),
        FieldSpec("topology.delimiterId", "str", "MODELLED", _NXT,
                  "the tap or ODP; the field the whole RCA turns on",
                  required=False),
        FieldSpec("topology.householdsBehindDelimiter", "int", "MODELLED", _NXT,
                  "blast radius; modelled because no source supplies it today",
                  required=False),
        FieldSpec("recentEvents", "list", "MODELLED", _NXT, required=False),
    ))

# --------------------------------------------------------------------- WFM
_TMF697 = "TM Forum TMF697 Work Order Management"

WFM_CONTRACT = SystemContract(
    system="WFM", transport="TMF697 REST, plus an event notification",
    provenance="STANDARD", specification=_TMF697,
    fields=(
        FieldSpec("id", "str", "STANDARD", _TMF697),
        FieldSpec("state", "str", "STANDARD", _TMF697,
                  "acknowledged, inProgress, completed, cancelled, failed"),
        FieldSpec("workOrderItem", "list", "STANDARD", _TMF697,
                  "the tasks on the order"),
        FieldSpec("appointment.validFor.startDateTime", "str", "STANDARD",
                  _TMF697, required=False),
        FieldSpec("relatedParty", "list", "STANDARD", _TMF697,
                  "the technician and the crew", required=False),
        FieldSpec("place", "list", "STANDARD", _TMF697, "the service address",
                  required=False),
        FieldSpec("characteristic", "list", "STANDARD", _TMF697,
                  "where operator-specific fields such as crew type live",
                  required=False),
    ))

# ------------------------------------------------------------------ jTrack
_TMF621 = "TM Forum TMF621 Trouble Ticket Management"

JTRACK_CONTRACT = SystemContract(
    system="jTrack",
    transport="TMF621 REST, plus TroubleTicketStatusChangeEvent notifications",
    provenance="STANDARD", specification=_TMF621,
    fields=(
        FieldSpec("id", "str", "STANDARD", _TMF621),
        FieldSpec("severity", "str", "STANDARD", _TMF621,
                  "critical, major, minor, warning"),
        FieldSpec("status", "str", "STANDARD", _TMF621,
                  "acknowledged, inProgress, pending, held, resolved, closed, "
                  "rejected"),
        FieldSpec("priority", "str", "STANDARD", _TMF621, required=False),
        FieldSpec("description", "str", "STANDARD", _TMF621),
        FieldSpec("relatedEntity", "list", "STANDARD", _TMF621,
                  "the service or resource the ticket is about", required=False),
        FieldSpec("note", "list", "STANDARD", _TMF621, required=False),
        FieldSpec("externalIdentifier", "list", "STANDARD", _TMF621,
                  "how a predictive ticket id is carried across", required=False),
        FieldSpec("statusChangeHistory", "list", "STANDARD", _TMF621,
                  "renamed from statusChange in TMF621 v5", required=False),
    ))

# ------------------------------------------------------------ CRM and billing
# MODELLED. TMF629 Customer Management and TMF666 Account Management define the
# shapes for customer and billing account, and the field names below follow them
# where they apply. Lifetime value, churn score and vulnerability flags are NOT in
# those standards: they are operator-specific, so those are invented.
_TMF629 = "TM Forum TMF629 Customer Management / TMF666 Account Management"
_CRM_MODELLED = "MODELLED, operator-specific and not in any standard"

CRM_CONTRACT = SystemContract(
    system="CRM", transport="TMF629 and TMF666 REST, or a nightly extract",
    provenance="MODELLED",
    specification=f"{_TMF629}; value and risk fields invented",
    fields=(
        FieldSpec("id", "str", "STANDARD", _TMF629, "account identifier"),
        FieldSpec("accountType", "str", "STANDARD", _TMF666 := _TMF629,
                  "residential, smb, enterprise, wholesale"),
        FieldSpec("billingAccount.state", "str", "STANDARD", _TMF629,
                  "TMF666: active, suspended, closed"),
        FieldSpec("agreement.validFor.endDateTime", "str", "STANDARD", _TMF629,
                  "contract end, which is what contract status derives from"),
        FieldSpec("monthlyRecurringRevenue", "float", "MODELLED", _CRM_MODELLED,
                  "the exposure the whole ranking rests on"),
        FieldSpec("lifetimeValue", "float", "MODELLED", _CRM_MODELLED,
                  "if supplied directly rather than derived from MRR and horizon"),
        FieldSpec("churnScore", "float", "MODELLED", _CRM_MODELLED,
                  "if a retention model already exists, it replaces the churn "
                  "calculation in commercial.py entirely"),
        FieldSpec("balanceOverdue", "float", "MODELLED", _CRM_MODELLED),
        FieldSpec("arrearsAgeDays", "int", "MODELLED", _CRM_MODELLED,
                  "payment status derives from this"),
        FieldSpec("medicalOrSafetyFlag", "bool", "MODELLED", _CRM_MODELLED,
                  "a PROTECTION. Its absence silently removes a safeguard, so its "
                  "presence must be verified rather than assumed"),
        FieldSpec("vulnerabilityFlag", "bool", "MODELLED", _CRM_MODELLED,
                  "a PROTECTION, same caution"),
        FieldSpec("lifelineSubsidised", "bool", "MODELLED", _CRM_MODELLED,
                  "a PROTECTION carrying a regulatory obligation"),
        FieldSpec("faultsLast90Days", "int", "MODELLED", _CRM_MODELLED,
                  "drives the churn uplift and the repeat-unresolved protection"),
    ))

CONTRACTS: tuple[SystemContract, ...] = (CPE_CONTRACT, NXT_CONTRACT,
                                         WFM_CONTRACT, JTRACK_CONTRACT,
                                         CRM_CONTRACT)


def contract_for(system: str) -> SystemContract:
    for contract in CONTRACTS:
        if contract.system.lower() == system.lower():
            return contract
    raise KeyError(system)


def summary() -> dict[str, object]:
    return {
        "systems": len(CONTRACTS),
        "standard": [c.system for c in CONTRACTS if c.provenance == "STANDARD"],
        "modelled": [c.system for c in CONTRACTS if c.provenance == "MODELLED"],
        "fields": sum(len(c.fields) for c in CONTRACTS),
        "modelled_fields": sum(1 for c in CONTRACTS for f in c.fields
                               if f.provenance == "MODELLED"),
        "warning": ("NXT is modelled end to end. Every field name in it is a "
                    "placeholder and should be confirmed against a real message "
                    "before any integration work starts."),
    }
