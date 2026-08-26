"""DvSum CADDI integration contract for the LPR service-assurance demo.

DvSum CADDI (Conversational Analytics for Data Driven Insights) is modelled as
an existing analytics and correlation layer that can support Call Center and
Network Operations.  This module intentionally exposes a contract only: the
demo does not claim a live CADDI endpoint, credentials, write path or internal
vendor data model.

Authoritative source systems retain ownership of their facts.  CADDI may
correlate and explain those facts, while LPR Operations remains authoritative
for incidents, approvals, dispatch, maintenance requests, repair, validation
and closure.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

CADDI_CANONICAL_NAME = "DvSum CADDI"
CADDI_EXPANSION = "Conversational Analytics for Data Driven Insights"
CADDI_SOURCE_LAYER = "dvsum_caddi"

_CAPABILITIES: tuple[dict[str, Any], ...] = (
    {
        "capability": "billing_and_account_context",
        "authoritative_sources": ["CSG"],
        "caddi_role": "correlate_and_present",
        "current_lpr_scope": "call_center",
    },
    {
        "capability": "outage_and_pnm_context",
        "authoritative_sources": ["OTS"],
        "caddi_role": "correlate_and_present",
        "current_lpr_scope": "call_center",
    },
    {
        "capability": "hfc_device_and_provisioning_context",
        "authoritative_sources": ["Intraway", "CommScope ServAssure NXT"],
        "caddi_role": "analytics_and_correlation",
        "current_lpr_scope": "call_center",
    },
    {
        "capability": "ftth_device_and_provisioning_context",
        "authoritative_sources": ["Symphonica", "CommScope ServAssure NXT"],
        "caddi_role": "analytics_and_correlation",
        "current_lpr_scope": "call_center",
    },
    {
        "capability": "node_outage_and_maintenance_context",
        "authoritative_sources": ["NEXT/Dvision", "LLA seven-day history"],
        "caddi_role": "analytics_and_correlation",
        "current_lpr_scope": "call_center",
    },
    {
        "capability": "premise_and_modem_context",
        "authoritative_sources": ["Dvision", "LLA seven-day history", "NXT"],
        "caddi_role": "analytics_and_correlation",
        "current_lpr_scope": "call_center",
    },
    {
        "capability": "wifi_context",
        "authoritative_sources": ["Plume"],
        "caddi_role": "future_analytics_and_presentation",
        "current_lpr_scope": "gap_not_connected",
    },
    {
        "capability": "customer_interaction",
        "authoritative_sources": ["Genesys"],
        "caddi_role": "agent_context_and_guidance",
        "current_lpr_scope": "call_center",
    },
    {
        "capability": "incident_dispatch_repair_and_closure",
        "authoritative_sources": ["LPR Operations", "jTrack", "NXT validation"],
        "caddi_role": "customer_safe_status_projection",
        "current_lpr_scope": "not_system_of_record",
    },
    {
        "capability": "24_hour_install_assurance_watch",
        "authoritative_sources": ["LPR Install Assurance", "NXT", "Provisioning systems"],
        "caddi_role": "analytics_agent_context_and_guidance",
        "current_lpr_scope": "contract_only_no_live_adapter",
    },
)


def caddi_contract() -> dict[str, Any]:
    """Return the canonical, JSON-serializable DvSum CADDI boundary contract."""

    return {
        "integration": "dvsum_caddi",
        "canonical_name": CADDI_CANONICAL_NAME,
        "product_expansion": CADDI_EXPANSION,
        "status": "contract_only",
        "live_connection": False,
        "current_lpr_deployment_scope": "call_center_via_genesys",
        "public_product_scope": "call_center_and_network_operations_analytics",
        "preferred_architecture": "augment_or_federate_not_duplicate",
        "source_of_truth_policy": (
            "Originating systems remain authoritative. DvSum CADDI supplies "
            "analytics, correlation and presentation; it does not silently "
            "replace billing, outage, provisioning, telemetry or repair truth."
        ),
        "operations_boundary": (
            "LPR Operations remains authoritative for root incidents, approvals, "
            "dispatch, maintenance requests, repair, validation and closure."
        ),
        "genesys_boundary": "Genesys remains the customer-interaction and agent-desktop channel.",
        "capabilities": deepcopy(list(_CAPABILITIES)),
        "required_analytical_lineage": [
            "source_layer",
            "analytical_record_id",
            "underlying_source_systems",
            "source_record_ids",
            "observed_at",
            "analyzed_at",
            "freshness",
            "confidence",
            "recommended_action",
            "authoritative_status_source",
        ],
        "known_gaps": [
            "No live DvSum CADDI endpoint or credential is configured in this demo.",
            "Plume Wi-Fi telemetry is not connected.",
            "Current LPR use is described as Call Center/Genesys; VPTO integration is not claimed.",
        ],
        "stage3_install_assurance": {
            "episode_authority": "lpr_install_assurance",
            "caddi_role": "analyze_and_present_customer_safe_context",
            "incident_authority": "lpr_operations",
            "production_write": False,
        },
    }


def project_install_assurance_context(
    *,
    episode: dict[str, Any],
    contact: dict[str, Any] | None = None,
    incident: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a customer-safe CADDI/Genesys projection for one install watch.

    The projection deliberately carries lineage and authority fields.  It is not
    a live CADDI payload and must not be treated as a vendor API contract.
    """

    incident = incident or {}
    contact = contact or {}
    source_ids = [episode.get("episode_id")]
    if contact.get("contact_id"):
        source_ids.append(contact["contact_id"])
    if incident.get("incident_id"):
        source_ids.append(incident["incident_id"])
    return {
        "source_layer": CADDI_SOURCE_LAYER,
        "analytical_record_id": f"CADDI-{episode.get('episode_id', 'UNKNOWN')}",
        "underlying_source_systems": [
            "LPR Install Assurance",
            "CommScope ServAssure NXT",
            "Provisioning systems",
            *( ["Genesys"] if contact else [] ),
            *( ["LPR Operations"] if incident else [] ),
        ],
        "source_record_ids": [value for value in source_ids if value],
        "observed_at": episode.get("last_observation_at"),
        "analyzed_at": episode.get("as_of_at"),
        "freshness": "current_to_watch_snapshot",
        "confidence": episode.get("diagnostic_confidence"),
        "recommended_action": episode.get("next_action"),
        "authoritative_status_source": "LPR Install Assurance",
        "canonical_name": CADDI_CANONICAL_NAME,
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
