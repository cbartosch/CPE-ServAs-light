"""Explicit CADI/Genesys integration contract.

CADI is an existing LPR call-center correlation and presentation layer. It is not
modelled here as a replacement source of truth. The systems that originate billing,
outage, provisioning, assurance, Wi-Fi and repair facts remain authoritative for
those facts; CADI assembles the context that a Genesys agent needs at contact time.

This module intentionally contains no live CADI client. The available endpoint,
field mapping, ownership, refresh guarantees and contractor roadmap still require
joint discovery with the CADI team. Keeping that status executable prevents a
static architecture diagram from being mistaken for a connected integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Coverage = Literal["existing", "gap", "boundary"]


@dataclass(frozen=True, slots=True)
class CadiCapability:
    """One stakeholder-supplied CADI capability and its authority boundary."""

    key: str
    label: str
    authoritative_sources: tuple[str, ...]
    cadi_role: str
    coverage: Coverage
    temporal_scope: str
    grain: str
    authority_note: str
    target_extension: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "authoritative_sources": list(self.authoritative_sources),
            "cadi_role": self.cadi_role,
            "coverage": self.coverage,
            "temporal_scope": self.temporal_scope,
            "grain": self.grain,
            "authority_note": self.authority_note,
            "target_extension": self.target_extension,
        }


CADI_CAPABILITIES: tuple[CadiCapability, ...] = (
    CadiCapability(
        key="billing",
        label="Billing and account context",
        authoritative_sources=("CSG",),
        cadi_role="Present account and billing context to the call-center agent.",
        coverage="existing",
        temporal_scope="Current account view; exact refresh SLA to confirm.",
        grain="customer / billing account",
        authority_note="CSG remains authoritative for billing and account state.",
        target_extension="Carry source timestamp and CSG record lineage with every value.",
    ),
    CadiCapability(
        key="outage_pnm",
        label="Outage and PNM context",
        authoritative_sources=("OTS",),
        cadi_role="Correlate the contact with outage and PNM context.",
        coverage="existing",
        temporal_scope="Current outage view; exact event latency to confirm.",
        grain="service / outage / network element",
        authority_note="OTS remains authoritative for the outage and PNM facts it publishes.",
        target_extension="Link the displayed outage to the canonical root incident.",
    ),
    CadiCapability(
        key="access_device_offline",
        label="Cable modem or FTTH device offline",
        authoritative_sources=(
            "Intraway HFC provisioning",
            "CommScope ServAssure NXT",
            "Symphonica FTTH",
        ),
        cadi_role="Show access-device registration/offline context across HFC and FTTH.",
        coverage="existing",
        temporal_scope="Current state; source precedence and latency to confirm.",
        grain="service / modem / ONT",
        authority_note=(
            "Intraway, NXT and Symphonica remain authoritative for their respective "
            "provisioning and assurance observations."
        ),
        target_extension=(
            "Make source disagreement and freshness visible instead of overwriting it."
        ),
    ),
    CadiCapability(
        key="node_outage_maintenance",
        label="Node-level outage and maintenance",
        authoritative_sources=("NEXT/Dvision real-time feed", "LLA seven-day history"),
        cadi_role="Present live node context and the preceding seven-day history.",
        coverage="existing",
        temporal_scope="Real time plus seven days of history, per stakeholder input.",
        grain="node / serving area",
        authority_note=(
            "The originating NEXT/Dvision and LLA feeds remain authoritative; exact "
            "product naming, ownership and conflict rules require confirmation."
        ),
        target_extension="Correlate node work with the operational incident and maintenance state.",
    ),
    CadiCapability(
        key="premise_modem_history",
        label="Premise and cable-modem history",
        authoritative_sources=("Dvision real-time feed", "LLA seven-day history"),
        cadi_role="Present modem-level current state and recent premise history.",
        coverage="existing",
        temporal_scope="Real time plus seven days of history, per stakeholder input.",
        grain="service / premise / cable modem",
        authority_note=(
            "The originating feeds remain authoritative; CADI correlates and presents them."
        ),
        target_extension="Add evidence lineage and a link to the assurance episode or incident.",
    ),
    CadiCapability(
        key="provisioning",
        label="Provisioning and cross-service diagnosis",
        authoritative_sources=("Intraway", "Symphonica FTTH"),
        cadi_role=(
            "Expose provisioning context, including cases where a reported video symptom "
            "is caused by the broadband service path."
        ),
        coverage="existing",
        temporal_scope="Current provisioning state; exact refresh SLA to confirm.",
        grain="service / product / device",
        authority_note="Intraway and Symphonica remain authoritative for provisioned state.",
        target_extension="Add governed next-best-action guidance without writing back implicitly.",
    ),
    CadiCapability(
        key="wifi",
        label="In-home Wi-Fi context",
        authoritative_sources=("Plume",),
        cadi_role="Not currently available in CADI.",
        coverage="gap",
        temporal_scope="No current CADI observation; target cadence to be agreed.",
        grain="gateway / mesh / client",
        authority_note="Plume would remain authoritative for the Wi-Fi telemetry it provides.",
        target_extension="Add one shared Plume adapter and publish a summarized finding to CADI.",
    ),
    CadiCapability(
        key="genesys_desktop",
        label="Call-center interaction and agent desktop",
        authoritative_sources=("Genesys",),
        cadi_role="Present correlated service context inside the Genesys call-center journey.",
        coverage="existing",
        temporal_scope="At customer interaction time.",
        grain="Genesys interaction / customer contact",
        authority_note="Genesys remains authoritative for the customer interaction record.",
        target_extension=(
            "Attach the interaction to the same service, episode and root incident IDs."
        ),
    ),
    CadiCapability(
        key="maintenance_repair_boundary",
        label="Maintenance and repair execution",
        authoritative_sources=(
            "Operations incident and work-order systems",
            "jTrack MR lifecycle",
            "NXT and service validation",
        ),
        cadi_role=(
            "Display a customer-safe status projection only; CADI is not the VPTO repair "
            "execution system."
        ),
        coverage="boundary",
        temporal_scope="Operational lifecycle; refresh and write-back policy to confirm.",
        grain="root incident / work order / MR",
        authority_note=(
            "Operations, jTrack and validation evidence remain authoritative for repair state "
            "and closure."
        ),
        target_extension="Project owner, current state and next update back to CADI/Genesys.",
    ),
)


def cadi_contract() -> dict[str, Any]:
    """Return the declared CADI layer without implying a live connection."""

    counts = {coverage: 0 for coverage in ("existing", "gap", "boundary")}
    for capability in CADI_CAPABILITIES:
        counts[capability.coverage] += 1
    return {
        "layer": "CADI",
        "integration_status": "contract_only",
        "live_connection": False,
        "owner_scope": "Call center / Genesys",
        "positioning": (
            "Existing LPR call-center correlation and presentation layer integrated with "
            "Genesys. Build on or federate with it before considering selective replacement."
        ),
        "source_of_truth_policy": (
            "CADI may correlate and present facts, but the originating billing, outage, "
            "provisioning, assurance, Wi-Fi and repair systems remain authoritative."
        ),
        "operations_boundary": (
            "Maintenance and repair remain in the Operations/VPTO workflow; CADI receives "
            "a customer-safe status projection rather than owning execution or closure."
        ),
        "preferred_pattern": "augment_or_federate",
        "replacement_policy": "selective_only_after_joint_discovery",
        "discovery_status": (
            "Stakeholder-supplied capability map. APIs, field definitions, source precedence, "
            "latency, retention, ownership and contractor roadmap are not yet verified."
        ),
        "summary": {
            "capability_domains": len(CADI_CAPABILITIES),
            "declared_existing": counts["existing"],
            "known_gaps": counts["gap"],
            "operations_boundaries": counts["boundary"],
        },
        "capabilities": [capability.to_dict() for capability in CADI_CAPABILITIES],
    }


def cadi_contract_rows() -> list[dict[str, str]]:
    """Flatten the CADI contract for dashboard tables."""

    return [
        {
            "Capability": capability.label,
            "Authoritative source(s)": ", ".join(capability.authoritative_sources),
            "CADI role": capability.cadi_role,
            "Coverage": capability.coverage,
            "Time scope": capability.temporal_scope,
            "Grain": capability.grain,
            "Target extension": capability.target_extension,
        }
        for capability in CADI_CAPABILITIES
    ]
