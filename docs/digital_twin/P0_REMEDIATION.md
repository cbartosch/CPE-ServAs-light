# P0 remediation status — v2.4.0 P0 Fixed R3 Hotfix5

Hotfix5 preserves all R3/Hotfix4 P0 closures and adds predictive/Care integration without relaxing any operating control.

| Control / finding | Hotfix5 status | Evidence |
|---|---|---|
| Canonical graph and fail-closed policy | **Preserved** | tests 23, 31 and quality groups 1-16 |
| Repeat cases create duplicate incidents | **Prevented** | same `root_incident_id`, supervisor escalation; tests 32/46 |
| Diagnosis / readiness / CPE swap / closure gates | **Preserved** | tests 33-34 |
| Windows SQLite/atomic publish | **Preserved** | tests 38/40 |
| Python 3.14.2 + host Ruff contract | **Preserved** | tests 39/41 |
| Predictive modem capability not exposed in Digital Twin Docker UI/API | **Fixed** | predictive scan API/UI + `predictive_modem_pulls` / `predictive_tickets`; tests 42-44 |
| Customer Care contacts not represented as governed ticket queue | **Fixed** | `care_tickets` + queue/detail API/UI; tests 42/44 |
| Predictive finding and later customer call could create duplicate work | **Prevented** | service/device/time correlation attaches care to canonical root incident; quality group 19 + tests 42/46 |
| Care review did not expose deterministic + LLM reconciliation context | **Fixed** | `care_ticket_reviews`; quality group 20 + tests 42/44/46 |
| Live closure not reflected in care queue | **Fixed** | live decision refreshes linked care status; test 45 |

Production integrations and writes remain out of scope. Hotfix5 provides synthetic collectors/contracts and the orchestration surfaces required to demonstrate the target operating model.

## Hotfix5.3 UI state remediation

- Fixed the keyed Streamlit widget-state defect that left Predictive Assurance and Customer Care `Run ID` fields blank after Generator created a run.
- Added latest-run recovery through the existing authenticated `GET /api/runs` endpoint after browser/session restart.
- Added a regression gate so the run-state propagation and no-run action-disable behavior cannot silently regress.

## Hotfix5.4 two-stack remediation

The separate host and Digital Twin Compose projects created duplicated lifecycle,
network, environment and UI state. Hotfix5.4 makes `docker-compose.yml` the single
authoritative stack, embeds the Digital Twin UI into the main Streamlit app, keeps
the Digital Twin API isolated as its own least-privilege service, and removes the
legacy host `docker-compose.digital-twin.yml` plus `.env.digital-twin.example` on
import.
