# Security and Control Design

## Default posture

- `APPLICATION_MODE=simulation`
- `PRODUCTION_WRITES_ENABLED=false`
- all operational systems are fixtures
- `MODEL_PROVIDER=fake`
- no provider API key is included
- Streamlit role selection is clearly labelled mock authentication

Changing the GUI cannot enable production writes. Real adapters, enterprise identity and the independent backend production-write settings would all be required.

## Approval and replay controls

1. Policy prepares a stable approval ID and idempotency key from durable incident state.
2. LangGraph pauses in a dedicated approval node containing exactly one interrupt and no external effect.
3. FastAPI checks approval status, required role and rationale rules.
4. FastAPI signs a short-lived HMAC token containing approval, incident, action, status and expiry claims.
5. The MCP tool validates the signature and every matching claim.
6. The effect store checks the idempotency key before execution.
7. The first effect consumes the approval.
8. Replaying the same key returns the stored result with `replayed=true`.
9. Reusing the approval for a different key is rejected as `APPROVAL_ALREADY_CONSUMED`.
10. Selecting a next-best action consumes the original approval and returns through policy for a fresh approval and token.

## Replay-safe histories

- Evidence is keyed by deterministic evidence ID.
- Actions are keyed by the idempotency key that produced them.
- Timeline events use a deterministic content/state key, not a list length or random UUID.
- Work-order and MR histories drop identical repeated revisions but preserve later status revisions.

These controls keep the audit trail consistent when a node, API request or MCP call is replayed.

## LLM boundary

- The model sees only the evidence and topology required for its task.
- Side-effecting tools are not bound to the model.
- RCA output is validated by Pydantic.
- Deterministic policy remains authoritative.
- Confidence never bypasses a responsibility-domain disagreement.
- The model may explain best and next-best action but cannot authorize or execute either.
- External provider failure follows the explicitly configured fail-closed or fake-fallback policy.

## Corporate TLS handling

Both runtime images trust the Debian system CA bundle. Optional corporate roots/issuing CAs are staged in `docker/certs/` and installed with `update-ca-certificates`. The project refuses non-CA certificates in its staging tools and does not use `--trusted-host` or disabled TLS verification.

## Production transition requirements

Before adapting the demonstration to production:

- replace mock roles with enterprise identity and backend RBAC;
- move secrets to a managed secret store;
- implement service-to-service TLS and authentication;
- replace fixture schemas with approved vendor contracts;
- minimize and redact PII at collection boundaries;
- add a transactional outbox around production writes;
- make decision records and audit retention immutable;
- add concurrency control, dead-letter handling and operational recovery;
- conduct threat modeling, penetration testing and readiness review;
- preserve fail-closed policy, typed actions and the independent two-key production-write posture.
