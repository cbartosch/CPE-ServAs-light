"""Explicit DvSum CADDI integration contract for the LPR assurance demo.

DvSum CADDI (Conversational Analytics for Data Driven Insights) is represented as
an AI analytics and correlation product for Call Center and Network Operations.
The stakeholder-supplied LPR deployment remains Call Center-facing through Genesys;
no deployment into Chuck/VPTO is claimed. CommScope ServAssure NXT is an important
source and normalization layer for subscriber and network performance evidence.

The contract deliberately separates analytical insight from authoritative state.
CSG, OTS, Intraway, ServAssure NXT, Symphonica, Dvision/NEXT, LLA history,
Plume, jTrack and the operational workflow remain authoritative for the facts and
lifecycle states they originate. CADDI may correlate, explain and recommend, but
must carry source lineage rather than silently replacing those systems.

This module contains no live DvSum CADDI or Genesys client. API shape, field
mapping, source precedence, latency, retention, ownership and contractor roadmap
still require joint discovery with LPR and DvSum. Keeping that status executable
prevents a product-positioning statement from being mistaken for a connected
integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

type Coverage = Literal["existing", "gap", "boundary"]


@dataclass(frozen=True, slots=True)
class CaddiCapability:
    """One declared DvSum CADDI capability and its authority boundary."""

    key: str
    label: str
    authoritative_sources: tuple[str, ...]
    caddi_role: str
    product_consumers: tuple[str, ...]
    declared_lpr_consumers: tuple[str, ...]
    coverage: Coverage
    temporal_scope: str
    grain: str
    authority_note: str
    target_extension: str

    @property
    def cadi_role(self) -> str:
        """Deprecated spelling retained for compatibility with Stage 1 consumers."""

        return self.caddi_role

    @property
    def consumers(self) -> tuple[str, ...]:
        """Return declared LPR consumers under the earlier field name."""

        return self.declared_lpr_consumers

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "authoritative_sources": list(self.authoritative_sources),
            "caddi_role": self.caddi_role,
            "cadi_role": self.caddi_role,
            "consumers": list(self.declared_lpr_consumers),
            "product_consumers": list(self.product_consumers),
            "declared_lpr_consumers": list(self.declared_lpr_consumers),
            "coverage": self.coverage,
            "temporal_scope": self.temporal_scope,
            "grain": self.grain,
            "authority_note": self.authority_note,
            "target_extension": self.target_extension,
        }


DVSUM_CADDI_CAPABILITIES: tuple[CaddiCapability, ...] = (
    CaddiCapability(
        key="billing",
        label="Billing and account context",
        authoritative_sources=("CSG",),
        caddi_role=(
            "Analyze and present account and billing context in the customer-service journey."
        ),
        product_consumers=("Call Center",),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="Current account view; exact refresh SLA to confirm.",
        grain="customer / billing account",
        authority_note="CSG remains authoritative for billing and account state.",
        target_extension="Carry source timestamp and CSG record lineage with every value.",
    ),
    CaddiCapability(
        key="outage_pnm",
        label="Outage and PNM context",
        authoritative_sources=("OTS",),
        caddi_role=(
            "Correlate a contact or network symptom with outage and PNM context."
        ),
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="Current outage view; exact event latency to confirm.",
        grain="service / outage / network element",
        authority_note="OTS remains authoritative for the outage and PNM facts it publishes.",
        target_extension="Link the analytical finding to the canonical root incident.",
    ),
    CaddiCapability(
        key="access_device_offline",
        label="Cable modem or FTTH device offline",
        authoritative_sources=(
            "Intraway HFC provisioning",
            "CommScope ServAssure NXT",
            "Symphonica FTTH",
        ),
        caddi_role=(
            "Analyze and present access-device registration and offline context across HFC "
            "and FTTH."
        ),
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="Current state; source precedence and latency to confirm.",
        grain="service / modem / ONT",
        authority_note=(
            "Intraway, ServAssure NXT and Symphonica remain authoritative for their "
            "respective provisioning and assurance observations."
        ),
        target_extension=(
            "Expose source disagreement, freshness and analytical confidence instead of "
            "overwriting one observation with another."
        ),
    ),
    CaddiCapability(
        key="node_outage_maintenance",
        label="Node-level outage and maintenance",
        authoritative_sources=("NEXT/Dvision real-time feed", "LLA seven-day history"),
        caddi_role=(
            "Analyze live node context and the preceding seven-day history for Care and "
            "Network Operations."
        ),
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="Real time plus seven days of history, per stakeholder input.",
        grain="node / serving area",
        authority_note=(
            "The originating NEXT/Dvision and LLA feeds remain authoritative; exact "
            "product naming, ownership and conflict rules require confirmation."
        ),
        target_extension=(
            "Correlate node work with the operational incident and maintenance state."
        ),
    ),
    CaddiCapability(
        key="premise_modem_history",
        label="Premise and cable-modem history",
        authoritative_sources=("Dvision real-time feed", "LLA seven-day history"),
        caddi_role=(
            "Analyze modem-level current state and recent premise history for subscriber "
            "triage and network diagnosis."
        ),
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="Real time plus seven days of history, per stakeholder input.",
        grain="service / premise / cable modem",
        authority_note=(
            "The originating feeds remain authoritative; DvSum CADDI correlates and "
            "analyzes them."
        ),
        target_extension="Add evidence lineage and a link to the assurance episode or incident.",
    ),
    CaddiCapability(
        key="provisioning",
        label="Provisioning and cross-service diagnosis",
        authoritative_sources=("Intraway", "Symphonica FTTH"),
        caddi_role=(
            "Analyze provisioning context, including cases where a reported video symptom "
            "is caused by the broadband service path."
        ),
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="Current provisioning state; exact refresh SLA to confirm.",
        grain="service / product / device",
        authority_note="Intraway and Symphonica remain authoritative for provisioned state.",
        target_extension=(
            "Add governed next-best-action guidance without implicit source-system write-back."
        ),
    ),
    CaddiCapability(
        key="wifi",
        label="In-home Wi-Fi context",
        authoritative_sources=("Plume",),
        caddi_role="Not currently available in the declared LPR DvSum CADDI scope.",
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="gap",
        temporal_scope="No current CADDI observation; target cadence to be agreed.",
        grain="gateway / mesh / client",
        authority_note="Plume would remain authoritative for the Wi-Fi telemetry it provides.",
        target_extension=(
            "Add one shared Plume adapter and publish a summarized finding to DvSum CADDI."
        ),
    ),
    CaddiCapability(
        key="genesys_desktop",
        label="Call-center interaction and agent experience",
        authoritative_sources=("Genesys",),
        caddi_role=(
            "Provide network-aware subscriber context and analytical guidance in the Genesys "
            "customer-service journey."
        ),
        product_consumers=("Call Center",),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="At customer interaction time.",
        grain="Genesys interaction / customer contact",
        authority_note="Genesys remains authoritative for the customer interaction record.",
        target_extension=(
            "Attach the interaction to the same service, episode and root incident IDs."
        ),
    ),
    CaddiCapability(
        key="maintenance_repair_boundary",
        label="Maintenance and repair analytics boundary",
        authoritative_sources=(
            "Operations incident and work-order systems",
            "jTrack MR lifecycle",
            "ServAssure NXT and service validation",
        ),
        caddi_role=(
            "Provide analytical context and a customer-safe status projection while the LPR "
            "operational workflow owns execution and closure."
        ),
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="boundary",
        temporal_scope="Operational lifecycle; refresh and write-back policy to confirm.",
        grain="root incident / work order / MR",
        authority_note=(
            "Operations, jTrack and validation evidence remain authoritative for repair state "
            "and closure."
        ),
        target_extension=(
            "Project owner, current state, next update and validated outcome back to CADDI "
            "and Genesys."
        ),
    ),
)


CADDI_REQUIRED_LINEAGE: tuple[str, ...] = (
    "analytical_record_id",
    "underlying_source_systems",
    "source_record_ids",
    "observed_at",
    "analyzed_at",
    "freshness_status",
    "confidence",
    "recommended_action",
    "authoritative_status_source",
)


def caddi_contract() -> dict[str, Any]:
    """Return the declared DvSum CADDI layer without implying a live connection."""

    counts = {coverage: 0 for coverage in ("existing", "gap", "boundary")}
    for capability in DVSUM_CADDI_CAPABILITIES:
        counts[capability.coverage] += 1
    return {
        "layer": "DvSum CADDI",
        "vendor": "DvSum",
        "product": "CADDI",
        "expanded_name": "Conversational Analytics for Data Driven Insights",
        "integration_status": "contract_only",
        "live_connection": False,
        "product_scope": "Call Center and Network Operations",
        "declared_lpr_deployment_scope": "Call Center via Genesys",
        "owner_scope": "Call Center via Genesys (declared LPR deployment)",
        "presentation_channels": ["Genesys"],
        "positioning": (
            "DvSum CADDI is an AI analytics and correlation product for Call Center and "
            "Network Operations. The declared LPR deployment remains Call Center-facing "
            "through Genesys; no VPTO/Network Operations deployment is claimed. Build on or "
            "federate with it before considering selective replacement."
        ),
        "nxt_relationship": (
            "CommScope ServAssure NXT collects and normalizes key network and subscriber "
            "performance information; DvSum CADDI analyzes it for customer-experience and "
            "network-health insight."
        ),
        "genesys_relationship": (
            "Genesys remains the interaction channel and agent experience; DvSum CADDI "
            "provides network-aware subscriber context and analytical guidance."
        ),
        "source_of_truth_policy": (
            "DvSum CADDI may correlate, analyze and recommend, but the originating billing, "
            "outage, provisioning, assurance, Wi-Fi and repair systems remain authoritative."
        ),
        "operations_boundary": (
            "The DvSum product supports Network Operations analytics, but the declared LPR "
            "deployment stays with the Call Center and is not presented as Chuck/VPTO's "
            "maintenance-and-repair tool. The LPR operational workflow remains authoritative "
            "for incident, dispatch, maintenance, MR, repair, validation and closure state."
        ),
        "preferred_pattern": "augment_or_federate",
        "replacement_policy": "selective_only_after_joint_discovery",
        "required_lineage": list(CADDI_REQUIRED_LINEAGE),
        "discovery_status": (
            "Product role is externally verified; the LPR-specific capability map is based on "
            "stakeholder input. APIs, fields, source precedence, latency, retention, ownership "
            "and contractor roadmap are not yet verified."
        ),
        "compatibility": {
            "deprecated_name": "CADI",
            "deprecated_module": "lpr_cpe_demo.cadi",
            "deprecated_route": "/api/integrations/cadi",
            "canonical_module": "lpr_cpe_demo.caddi",
            "canonical_route": "/api/integrations/caddi",
            "canonical_query_view": "caddi",
        },
        "summary": {
            "capability_domains": len(DVSUM_CADDI_CAPABILITIES),
            "declared_existing": counts["existing"],
            "known_gaps": counts["gap"],
            "operations_boundaries": counts["boundary"],
        },
        "capabilities": [
            capability.to_dict() for capability in DVSUM_CADDI_CAPABILITIES
        ],
    }


def caddi_contract_rows() -> list[dict[str, str]]:
    """Flatten the DvSum CADDI contract for dashboard tables."""

    return [
        {
            "Capability": capability.label,
            "Authoritative source(s)": ", ".join(capability.authoritative_sources),
            "DvSum CADDI role": capability.caddi_role,
            "Product consumer(s)": ", ".join(capability.product_consumers),
            "Declared LPR consumer(s)": ", ".join(
                capability.declared_lpr_consumers
            ),
            "Coverage": capability.coverage,
            "Time scope": capability.temporal_scope,
            "Grain": capability.grain,
            "Target extension": capability.target_extension,
        }
        for capability in DVSUM_CADDI_CAPABILITIES
    ]
