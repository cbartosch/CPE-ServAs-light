# Pinned Framework Versions

The Docker images install exact versions so the demonstration is reproducible. The target-laptop framework check reads the requirement files and fails if the installed metadata does not match every pin.

| Package | Version | Purpose |
|---|---:|---|
| Python | 3.12 | Runtime base image |
| FastAPI | 0.141.1 | Query and command API |
| Uvicorn | 0.52.3 | ASGI server |
| Streamlit | 1.61.1 | Operations cockpit and decision GUI |
| LangChain | 1.3.14 | Structured LLM integrations |
| LangGraph | 1.2.11 | Durable workflow and human interrupts |
| LangGraph PostgreSQL checkpointer | 3.1.2 | Persistent graph checkpoints |
| MCP Python SDK | 2.0.0 | Installed compatibility surface |
| Pydantic | 2.13.4 | Typed contracts and structured outputs |
| SQLAlchemy | 2.0.50 | Operational read model |
| PostgreSQL image | 17-alpine | Read model and graph checkpoints |

The exact version endpoints for the principal framework pins were verified on PyPI during the 17 August 2026 revision. Availability on PyPI does not replace the bundle's runtime compatibility checks; the complete Docker verification imports the installed APIs, compares the separate MCP service image against `requirements-mcp.txt`, executes a LangGraph interrupt/resume flow, starts Streamlit and tests the PostgreSQL checkpoint path.

The mockup implements its small strict/stateless MCP HTTP subset explicitly so approval-token, idempotency and header behavior are visible and testable. The SDK remains installed for protocol-family compatibility and future migration to SDK-native client/server objects.
