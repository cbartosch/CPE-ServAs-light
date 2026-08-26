# CADI / Genesys Integration Contract — Stage 1

## Purpose

Make CADI explicit in the LPR assurance architecture without creating a second
source of truth or claiming a live integration that has not been verified.

CADI is treated as the existing LPR call-center correlation and presentation
layer integrated with Genesys. It assembles the service context an agent needs
when a customer contacts the call center. The originating systems remain
authoritative for billing, outage, provisioning, assurance, Wi-Fi and repair
facts.

This document is a **stakeholder-supplied current-state contract**. The CADI API,
field definitions, identifier rules, source precedence, refresh guarantees,
retention, ownership and contractor roadmap still require joint discovery.

## Positioning

The preferred target is to **augment or federate with CADI**:

```text
Authoritative source systems
        │
        ├──────────────► CADI / Genesys call-center context
        │                            │
        └──────────────► Assurance evidence and orchestration
                                     │
                         customer-safe status back to CADI
```

Selective replacement is considered only after discovery proves that a specific
CADI component is inaccurate, inaccessible, unmaintainable or unable to meet the
required operating contract. Stage 1 does not make that decision.

## Declared current-state capability map

| Capability | Authoritative source(s) | CADI role | Current state |
|---|---|---|---|
| Billing and account context | CSG | Present billing/account context to the agent | Declared existing |
| Outage and PNM context | OTS | Correlate the contact with outage/PNM context | Declared existing |
| Cable modem / FTTH device offline | Intraway HFC provisioning, CommScope ServAssure NXT, Symphonica FTTH | Present access-device registration/offline state | Declared existing |
| Node-level outage and maintenance | NEXT/Dvision real-time feed, LLA seven-day history | Present live node context and recent history | Declared existing; exact product naming and ownership to confirm |
| Premise / cable-modem context | Dvision real-time feed, LLA seven-day history | Present modem-level current state and recent premise history | Declared existing |
| Provisioning and cross-service diagnosis | Intraway, Symphonica FTTH | Expose provisioning context, including broadband causes of reported video symptoms | Declared existing |
| In-home Wi-Fi | Plume | Not currently in CADI | Known gap |
| Agent desktop and contact | Genesys | Present the correlated context in the call-center journey | Declared existing |
| Maintenance and repair | Operations, jTrack MR lifecycle, NXT/service validation | Display a customer-safe status projection only | Explicit boundary: CADI is not the VPTO repair execution system |

`NEXT/Dvision` is retained from the stakeholder terminology. The exact system
name, feed owner and relationship to CommScope ServAssure NXT must be confirmed.

## Source-of-truth policy

1. **CSG** remains authoritative for billing and account state.
2. **OTS** remains authoritative for the outage/PNM facts it publishes.
3. **Intraway, NXT and Symphonica** remain authoritative for their respective
   provisioning and assurance observations.
4. **Dvision/NEXT and LLA** remain authoritative for the live and historical
   network context they originate.
5. **Plume** would remain authoritative for Wi-Fi telemetry when connected.
6. **Genesys** remains authoritative for the customer interaction record.
7. **Operations, work-order and jTrack systems** remain authoritative for
   maintenance, repair and MR lifecycle.
8. **NXT and service tests** remain authoritative evidence for restoration
   validation.
9. CADI may correlate, summarize and present these facts, but must carry source
   record, observation timestamp, retrieval timestamp and freshness.
10. Source disagreement must be visible; CADI or the assurance layer must not
    silently overwrite one source with another.

## Target identity chain

```text
customer_id
billing_account_id
service_id
device_id / serial_number / MAC
technology
node_id or OLT/port
tap_id or ODP_id
cadi_context_id
genesys_interaction_id
assurance_episode_id (future Stage 3)
root_incident_id
care_ticket_id
work_order_id
mr_id
```

Every projected value should eventually carry:

```text
source_system
source_record_id
observed_at
retrieved_at
effective_at
freshness_status
data_quality
correlation_method
```

## Operating boundary

CADI stays with the call center. The Operations/VPTO surface remains responsible
for:

- root incidents and operational ownership;
- remote actions and approvals;
- Clean Boots dispatch and evidence;
- HFC tap / PON ODP handoff;
- jTrack MR acceptance, repair and completion;
- maintenance and repair status;
- objective validation and closure.

CADI should receive a customer-safe projection such as current owner, current
state, next update, repair-in-progress and restored-under-observation. It should
not become the execution or closure system.

## Discovery gate before a live adapter

Stage 1 is signed off only as an explicit architecture contract. A live CADI
adapter requires answers to the following:

- Does CADI expose an API, event feed, database view or only a UI integration?
- Which identifiers are authoritative for customer, service and device matching?
- What is the source precedence when CADI inputs disagree?
- What are the refresh and stale-data guarantees for each source?
- Does CADI store source copies or query them at interaction time?
- Can CADI accept an assurance episode, root incident and repair reference?
- Can it display work already in progress and the next committed update?
- Can external recommendations be surfaced in Genesys with provenance?
- What write-back is supported and what approvals govern it?
- What is owned by the LPR team versus the current contractor?
- Why do Maintenance and Repair stakeholders report that CADI is not helping?
- Is the missing Wi-Fi context best integrated through one shared Plume adapter?

## Stage boundary

This Stage 1 implementation provides:

- an executable CADI capability and authority contract;
- API endpoints that expose the contract;
- explicit CADI/Genesys presentation in Executive, Customer Care, legacy Control
  Tower and Operations views;
- a data-contract work item for a future live adapter;
- tests that prevent CADI from being represented as an authoritative repair or
  billing system.

It does **not** provide:

- a live CADI or Genesys client;
- source-system credentials or data;
- a live CADI data adapter or source-system connection;
- the 24-Hour Install Assurance Watch (Stage 3);
- a decision to replace CADI.

## Stage 2 relationship

Stage 2 applies the shared measurement contract to Digital Twin and Operations
evidence while preserving this CADI boundary. CADI is still contract-only, and
no CADI-derived value is treated as authoritative or silently substituted into
the canonical projections.
