"""Explicit DvSum DALLI integration contract for the LPR assurance demo.

DvSum DALLI is represented as
an AI analytics and correlation product for Call Center and Network Operations.
The stakeholder-supplied LPR deployment remains Call Center-facing through Genesys;
no deployment into Chuck/VPTO is claimed. CommScope ServAssure NXT is an important
source and normalization layer for subscriber and network performance evidence.

The contract deliberately separates analytical insight from authoritative state.
CSG, OTS, Intraway, ServAssure NXT, Symphonica, Dvision/NEXT, LLA history,
Plume, jTrack and the operational workflow remain authoritative for the facts and
lifecycle states they originate. DALLI may correlate, explain and recommend, but
must carry source lineage rather than silently replacing those systems.

This module contains no live DvSum DALLI or Genesys client. API shape, field
mapping, source precedence, latency, retention, ownership and contractor roadmap
still require joint discovery with LPR and DvSum. Keeping that status executable
prevents a product-positioning statement from being mistaken for a connected
integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Coverage = Literal["existing", "gap", "boundary"]


DALLI_CANONICAL_NAME = "DvSum DALLI"
DALLI_SOURCE_LAYER = "dvsum_dalli"
DALLI_PUBLIC_COMPATIBILITY_NAME = "DvSum CADDI"


@dataclass(frozen=True, slots=True)
class DalliCapability:
    """One declared DvSum DALLI capability and its authority boundary."""

    key: str
    label: str
    authoritative_sources: tuple[str, ...]
    dalli_role: str
    product_consumers: tuple[str, ...]
    declared_lpr_consumers: tuple[str, ...]
    coverage: Coverage
    temporal_scope: str
    grain: str
    authority_note: str
    target_extension: str

    @property
    def caddi_role(self) -> str:
        """Former double-D field retained for compatibility."""

        return self.dalli_role

    @property
    def cadi_role(self) -> str:
        """Original single-D field retained for compatibility."""

        return self.dalli_role

    @property
    def consumers(self) -> tuple[str, ...]:
        """Return declared LPR consumers under the earlier field name."""

        return self.declared_lpr_consumers

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "authoritative_sources": list(self.authoritative_sources),
            "dalli_role": self.dalli_role,
            "caddi_role": self.dalli_role,
            "cadi_role": self.dalli_role,
            "consumers": list(self.declared_lpr_consumers),
            "product_consumers": list(self.product_consumers),
            "declared_lpr_consumers": list(self.declared_lpr_consumers),
            "coverage": self.coverage,
            "temporal_scope": self.temporal_scope,
            "grain": self.grain,
            "authority_note": self.authority_note,
            "target_extension": self.target_extension,
        }


DVSUM_DALLI_CAPABILITIES: tuple[DalliCapability, ...] = (
    DalliCapability(
        key="billing",
        label="Billing and account context",
        authoritative_sources=("CSG",),
        dalli_role=(
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
    DalliCapability(
        key="outage_pnm",
        label="Outage and PNM context",
        authoritative_sources=("OTS",),
        dalli_role=(
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
    DalliCapability(
        key="access_device_offline",
        label="Cable modem or FTTH device offline",
        authoritative_sources=(
            "Intraway HFC provisioning",
            "CommScope ServAssure NXT",
            "Symphonica FTTH",
        ),
        dalli_role=(
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
    DalliCapability(
        key="node_outage_maintenance",
        label="Node-level outage and maintenance",
        authoritative_sources=("NEXT/Dvision real-time feed", "LLA seven-day history"),
        dalli_role=(
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
    DalliCapability(
        key="premise_modem_history",
        label="Premise and cable-modem history",
        authoritative_sources=("Dvision real-time feed", "LLA seven-day history"),
        dalli_role=(
            "Analyze modem-level current state and recent premise history for subscriber "
            "triage and network diagnosis."
        ),
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="existing",
        temporal_scope="Real time plus seven days of history, per stakeholder input.",
        grain="service / premise / cable modem",
        authority_note=(
            "The originating feeds remain authoritative; DvSum DALLI correlates and "
            "analyzes them."
        ),
        target_extension="Add evidence lineage and a link to the assurance episode or incident.",
    ),
    DalliCapability(
        key="provisioning",
        label="Provisioning and cross-service diagnosis",
        authoritative_sources=("Intraway", "Symphonica FTTH"),
        dalli_role=(
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
    DalliCapability(
        key="wifi",
        label="In-home Wi-Fi context",
        authoritative_sources=("Plume",),
        dalli_role="Not currently available in the declared LPR DvSum DALLI scope.",
        product_consumers=("Call Center", "Network Operations"),
        declared_lpr_consumers=("Call Center",),
        coverage="gap",
        temporal_scope="No current DALLI observation; target cadence to be agreed.",
        grain="gateway / mesh / client",
        authority_note="Plume would remain authoritative for the Wi-Fi telemetry it provides.",
        target_extension=(
            "Add one shared Plume adapter and publish a summarized finding to DvSum DALLI."
        ),
    ),
    DalliCapability(
        key="genesys_desktop",
        label="Call-center interaction and agent experience",
        authoritative_sources=("Genesys",),
        dalli_role=(
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
    DalliCapability(
        key="maintenance_repair_boundary",
        label="Maintenance and repair analytics boundary",
        authoritative_sources=(
            "Operations incident and work-order systems",
            "jTrack MR lifecycle",
            "ServAssure NXT and service validation",
        ),
        dalli_role=(
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
            "Project owner, current state, next update and validated outcome back to DALLI "
            "and Genesys."
        ),
    ),
)


DALLI_REQUIRED_LINEAGE: tuple[str, ...] = (
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


def dalli_contract() -> dict[str, Any]:
    """Return the declared DvSum DALLI layer without implying a live connection."""

    counts = {coverage: 0 for coverage in ("existing", "gap", "boundary")}
    for capability in DVSUM_DALLI_CAPABILITIES:
        counts[capability.coverage] += 1
    return {
        "layer": DALLI_CANONICAL_NAME,
        "canonical_name": DALLI_CANONICAL_NAME,
        "source_layer": DALLI_SOURCE_LAYER,
        "vendor": "DvSum",
        "product": "DALLI",
        "expanded_name": None,
        "naming_note": (
            "DvSum DALLI is the LPR project-facing display name. This demo does not "
            "assert an acronym expansion."
        ),
        "integration_status": "contract_only",
        "live_connection": False,
        "product_scope": "Call Center and Network Operations",
        "declared_lpr_deployment_scope": "Call Center via Genesys",
        "owner_scope": "Call Center via Genesys (declared LPR deployment)",
        "presentation_channels": ["Genesys"],
        "positioning": (
            "DvSum DALLI is an AI analytics and correlation product for Call Center and "
            "Network Operations. The declared LPR deployment remains Call Center-facing "
            "through Genesys; no VPTO/Network Operations deployment is claimed. Build on or "
            "federate with it before considering selective replacement."
        ),
        "nxt_relationship": (
            "CommScope ServAssure NXT collects and normalizes key network and subscriber "
            "performance information; DvSum DALLI analyzes it for customer-experience and "
            "network-health insight."
        ),
        "genesys_relationship": (
            "Genesys remains the interaction channel and agent experience; DvSum DALLI "
            "provides network-aware subscriber context and analytical guidance."
        ),
        "source_of_truth_policy": (
            "DvSum DALLI may correlate, analyze and recommend, but the originating billing, "
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
        "required_lineage": list(DALLI_REQUIRED_LINEAGE),
        "discovery_status": (
            "Product role is externally verified; the LPR-specific capability map is based on "
            "stakeholder input. APIs, fields, source precedence, latency, retention, ownership "
            "and contractor roadmap are not yet verified."
        ),
        "compatibility": {
            "legacy_display_names": [
                DALLI_PUBLIC_COMPATIBILITY_NAME,
                "CADDI",
                "CADI",
                "Dali",
            ],
            "legacy_modules": ["lpr_cpe_demo.caddi", "lpr_cpe_demo.cadi"],
            "legacy_routes": ["/api/integrations/caddi", "/api/integrations/cadi"],
            "canonical_module": "lpr_cpe_demo.dalli",
            "canonical_route": "/api/integrations/dalli",
            "canonical_query_view": "dalli",
        },
        "summary": {
            "capability_domains": len(DVSUM_DALLI_CAPABILITIES),
            "declared_existing": counts["existing"],
            "known_gaps": counts["gap"],
            "operations_boundaries": counts["boundary"],
        },
        "capabilities": [
            capability.to_dict() for capability in DVSUM_DALLI_CAPABILITIES
        ],
    }


def dalli_contract_rows() -> list[dict[str, str]]:
    """Flatten the DvSum DALLI contract for dashboard tables."""

    return [
        {
            "Capability": capability.label,
            "Authoritative source(s)": ", ".join(capability.authoritative_sources),
            "DvSum DALLI role": capability.dalli_role,
            "Product consumer(s)": ", ".join(capability.product_consumers),
            "Declared LPR consumer(s)": ", ".join(
                capability.declared_lpr_consumers
            ),
            "Coverage": capability.coverage,
            "Time scope": capability.temporal_scope,
            "Grain": capability.grain,
            "Target extension": capability.target_extension,
        }
        for capability in DVSUM_DALLI_CAPABILITIES
    ]


def project_install_assurance_context(
    *,
    episode: dict[str, Any],
    contact: dict[str, Any] | None = None,
    incident: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a customer-safe DvSum DALLI/Genesys projection for one install watch.

    The projection carries lineage and authority fields. It is not a live DALLI
    payload and must not be treated as a vendor API contract.
    """

    incident = incident or {}
    contact = contact or {}
    source_ids = [episode.get("episode_id")]
    if contact.get("contact_id"):
        source_ids.append(contact["contact_id"])
    if incident.get("incident_id"):
        source_ids.append(incident["incident_id"])
    return {
        "source_layer": DALLI_SOURCE_LAYER,
        "analytical_record_id": f"DALLI-{episode.get('episode_id', 'UNKNOWN')}",
        "underlying_source_systems": [
            "LPR Install Assurance",
            "CommScope ServAssure NXT",
            "Provisioning systems",
            *(["Genesys"] if contact else []),
            *(["LPR Operations"] if incident else []),
        ],
        "source_record_ids": [value for value in source_ids if value],
        "observed_at": episode.get("last_observation_at"),
        "analyzed_at": episode.get("as_of_at"),
        "freshness_status": "current_to_watch_snapshot",
        "freshness": "current_to_watch_snapshot",
        "confidence": episode.get("diagnostic_confidence"),
        "recommended_action": episode.get("next_action"),
        "authoritative_status_source": "LPR Install Assurance",
        "canonical_name": DALLI_CANONICAL_NAME,
        "genesys_interaction_id": contact.get("genesys_interaction_id"),
        "episode_id": episode.get("episode_id"),
        "service_id": episode.get("service_id"),
        "device_id": episode.get("device_id"),
        "technology": episode.get("technology"),
        "watch_status": episode.get("lifecycle_state"),
        "health_state": episode.get("health_state"),
        "watch_age_hours": episode.get("age_hours"),
        "effective_maturity_at": episode.get("effective_maturity_at"),
        "network_detected_before_call": episode.get("network_before_call"),
        "leading_finding": episode.get("leading_finding"),
        "actions_already_taken": episode.get("action_types", []),
        "current_owner": episode.get("current_owner"),
        "root_incident_id": episode.get("incident_id"),
        "work_order_ids": episode.get("work_order_ids", []),
        "mr_ids": episode.get("mr_ids", []),
        "next_update_at": episode.get("next_update_at"),
        "customer_guidance": (
            "Attach the interaction to the existing assurance episode and root incident; "
            "do not restart completed diagnostics or create duplicate work."
        ),
        "live_connection": False,
        "production_write": False,
    }
