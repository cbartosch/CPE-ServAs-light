# Stage 3 DvSum CADDI naming repair candidate

- Canonical display name: **DvSum CADDI**
- Canonical API: `GET /api/integrations/caddi`
- Canonical navigation: `digital-twin?view=caddi`
- Compatibility aliases: CADDI/CADI imports, routes, and query values retained
- Focused regression gate: **214 passed**
- Stage 2 semantic projection: unchanged
- Stage 3 install-watch behavior: unchanged
- Standalone Control Tower HTML: regenerated with DvSum CADDI labels
- Python compileall: pass
- Ruff: target-laptop gate required because the executable was unavailable in the packaging runtime

See `docs/STAGE3_DVSUM_CADDI_AUDIT.md`.

---

# v1.27.16 target Ruff closure

- Removes the two remaining target-side Ruff 0.13.3 findings from v1.27.15.
- Complete collection: **916 tests**; **914 passed**, **2 framework-dependent skips**, **0 failed**, executed in bounded file groups.
- Nine-scenario matrix: **PASS**.
- Manifest verification: **PASS** after regeneration.
- Preserves all application and runtime behavior from v1.27.15.
- Requires the complete pytest suite, exact Ruff 0.13.3 check, scenario matrix, manifest verification, clean-clone verification, and Docker runtime smoke before push.

# v1.27.15 runtime connectivity and legacy-child compatibility

- Application collection: **914 tests**.
- Complete isolated test inventory: **912 passed, 2 framework skips**.
- Nine-scenario governed workflow matrix: **PASS**.
- Browser layout harness: **PASS** at 1600×900, 1366×768, 1024×768 and 600×800.
- Parent Digital Twin executive projection remains available when the newest optional legacy Install Assurance child lacks current-schema context data.
- Direct access to that incomplete child returns a structured HTTP 409 and does not mutate the parent run.
- Scenario launch uses a separate 240-second request budget and exposes progress and diagnostics.
- Startup scripts force-recreate the Docker services and run `scripts/runtime_smoke.py` inside the UI container.
- Target-side mandatory gate: Python 3.14.7, pytest 9.0.2, Ruff 0.13.3, Docker Compose configuration and runtime connectivity smoke.

# Test Report

## Stage 2 semantic reconciliation candidate

- Base: signed-off Stage 1 commit `acf26bb6cfbf3eea41ecf89871bc7e9b3e73c5b7`
- Scope: shared measurement semantics only
- Install assurance: deliberately excluded until Stage 2 sign-off

### Stage 2 acceptance results

| Gate | Result |
|---|---:|
| Shared entity-grain and metric contract | PASS |
| Complete Digital Twin projection and reconciliation invariants | PASS |
| Live Operations projection using the same schema | PASS |
| Active-run versus Planning-model separation | PASS |
| Full-population totals beyond pagination limits | PASS |
| Predictive child-scan isolation | PASS |
| DvSum CADDI Stage 1 boundary retained | PASS |
| Focused API, dashboard, DvSum CADDI, HTML, telemetry and semantic tests | **201 PASS** |
| Python source, scripts and tests compile | PASS |
| `git diff --check` | PASS |

The candidate adds a 5,101-contact regression. It proves that Executive and Care
headline totals are calculated from complete aggregates rather than the 5,000-row
dataset display cap or the 200-row Care display page.

### Inherited repository gates

An expanded audit was also run against the Stage 2 tree and repeated against the
signed-off Stage 1 base. The same inherited failures occur in both:

- workflow fixtures create approval tokens without the idempotency key now required
  by the execution guard;
- one UI test expects a Python 3.12 base although the committed Dockerfiles use
  Python 3.14.2;
- the asset policy test rejects the existing trusted-host fallback;
- two MCP-control fixtures omit the idempotency-key claim;
- the Digital Twin reachability heuristic treats FastAPI route functions as
  unreachable application symbols.

These are not introduced or hidden by Stage 2. They remain separate remediation
work and are not included in this stage-gated semantic change.

### Target-laptop gate

The packaging runtime could not obtain the pinned Ruff executable. Run on Windows:

```powershell
python -m ruff check src scripts tests
python -m pytest -q `
  tests/test_measurement_semantics.py `
  tests/test_api.py `
  tests/test_digital_twin_p0.py `
  tests/test_dashboard.py `
  tests/test_cadi.py `
  tests/test_html_report.py `
  tests/test_lint_baseline.py `
  tests/test_telemetry.py `
  tests/test_bundle_integrity.py
```

---

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
