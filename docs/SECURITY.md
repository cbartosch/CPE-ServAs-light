# Security Posture

This is a simulation-only reference implementation.

## Enforced in the bundle

- production writes disabled by default;
- model cannot call action tools directly;
- action type, incident and signed approval claims must match;
- idempotency keys are persistent;
- one approval cannot authorize a different second effect;
- role authorization is checked at the API/service boundary;
- override, rejection and request-more decisions require a reason;
- model output is validated into a strict Pydantic schema;
- no real customer PII is included in fixtures;
- no API keys are included in `.env`.

## Required before production

- enterprise OIDC and backend-enforced RBAC;
- secrets manager rather than `.env`;
- TLS, network segmentation and egress controls;
- vendor API authentication, rate limits and contract tests;
- immutable centralized audit logging;
- PII classification, retention and redaction policy;
- threat modeling and penetration testing;
- model prompt-injection and data-exfiltration controls;
- operational change management and rollback testing.
