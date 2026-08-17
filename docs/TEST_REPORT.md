# Test Report

## Revision under test

- Bundle: **LPR CPE Service Assurance Demo v1.2 improved**
- Assembly date: **17 August 2026**
- Assembly host: Linux x86_64, Python 3.13.5
- Docker Engine in assembly host: **not available**

The local gate used the portable workflow runtime, SQLite operational store, in-process MCP client, FastAPI TestClient and strict HTTP MCP endpoint tests. Docker-only framework and persistence checks are included in the bundle for execution on the target laptop.

## Results executed in the assembly environment

| Gate | Result |
|---|---:|
| Compose duplicate-key and structural validation | PASS |
| Shell-script syntax validation | PASS |
| Python `compileall` for source, tests and scripts | PASS |
| Automated tests | **35 PASS** |
| Measured source coverage | **84.63%** |
| Coverage threshold | **80% PASS** |
| Nine-scenario workflow matrix | PASS |
| FastAPI scenario, role and approval tests | PASS |
| Strict HTTP MCP profile/header tests | PASS |
| Live FastAPI-to-HTTP-MCP workflows (remote close plus failed-plant re-RCA/MR update) | PASS |
| MCP idempotency and approval-consumption tests | PASS |
| Fake/provider-fallback boundary tests | PASS |
| Safe environment-default tests | PASS |
| Corporate CA and split-image asset tests | PASS |

## Scenario matrix

| Scenario | Terminal result | Control demonstrated |
|---|---|---|
| `bounded_remote_failure` | Escalated | Two failed remote attempts reach the configured ceiling instead of looping. |
| `hfc_common_cause` | Closed | Child case attaches to a plant/common-cause parent and uses the parent SLA authority without a CPE visit. |
| `hfc_failed_plant_action_rerca` | Closed | First plant action fails, new evidence returns the case to RCA, and the same jTrack MR is updated for a second attempt. |
| `hfc_remote_fail_clean_success` | Closed | Failed remote action is recorded before Clean Boots dispatch. |
| `hfc_remote_success` | Closed | One approved remote action restores service without field work. |
| `hfc_self_help_success` | Closed | Guided self-help closes only after post-action validation. |
| `pon_odp_handover` | Closed | Clean Boots establishes the ODP boundary and creates one linked jTrack MR. |
| `pon_reverse_handover` | Closed | Dirty Boots restores plant, then the same incident returns to Clean Boots for the remaining in-home fault. |
| `rca_disagreement_gate` | Closed | High confidence still stops for a human when deterministic and assisted responsibility domains differ. |

## Controls exercised

The automated suite covers:

- deterministic-versus-assisted responsibility-domain disagreement;
- conservative fusion using the lower confidence rather than allowing the LLM to raise the deterministic confidence;
- restart-stable action and approval key derivation;
- delimiter-sensitive idempotency keys;
- replay-safe timeline, action, work-order and MR histories;
- same-key replay returning the stored result;
- consumed approval rejection for a different effect;
- tool/action, incident and approval-claim checks;
- next-best-action override returning through policy and receiving a fresh approval;
- role authorization for human decisions;
- parent/child SLA authority and preservation of the child clock;
- bounded remote, field, MR and diagnostic loops;
- HFC tap, PON ODP and reverse-handover paths;
- command acknowledgement separated from restoration verification;
- exact MCP compatibility-profile configuration and fail-fast mismatch handling;
- safe simulation defaults and no embedded provider key;
- Compose service health dependencies;
- Streamlit source parsing and presence of cockpit, incident, decision and model-monitor surfaces;
- corporate CA staging support without disabling TLS verification.

## Not executed in the assembly environment

The assembly host had no Docker Engine and could not install the exact pinned runtime packages from the network. The following remain mandatory target-laptop checks:

- Docker image build and container startup;
- live Streamlit server and browser session;
- exact pinned Streamlit, LangChain, LangGraph, MCP and provider package imports;
- real LangGraph interrupt/resume execution;
- PostgreSQL-backed LangGraph checkpoint persistence;
- service recreation and same-thread resume from PostgreSQL;
- end-to-end FastAPI-to-network-MCP execution through the running Compose services;
- external OpenAI or Anthropic API calls.

## Full target-laptop Docker gate

Run one of the complete verification scripts:

```powershell
.\scripts\verify_docker.ps1
```

```bash
./scripts/verify_docker.sh
```

The scripts:

1. build the separate application and MCP images;
2. start PostgreSQL, MCP, FastAPI and Streamlit and wait for healthy status;
3. verify the live health endpoints;
4. drive an incident and human approval through FastAPI to the network MCP service;
5. compare every installed application/test dependency with its exact requirement pin;
6. compare the running MCP service image versions with `requirements-mcp.txt`;
7. import the required Streamlit, LangChain, LangGraph, MCP and PostgreSQL-checkpointer APIs;
8. run an actual LangGraph interrupt/resume smoke graph;
9. start Streamlit and check `/_stcore/health`;
10. recreate the workflow service against the same PostgreSQL database and resume its pending approval;
11. run all nine workflow scenarios;
12. compile all source, test and script files;
13. rerun pytest with the 80% coverage gate.

See `BUILD_TEST_REPORT.txt` for the concise packaging record and `docs/RUNBOOK.md` for troubleshooting.
