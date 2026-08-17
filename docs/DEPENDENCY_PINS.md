# Dependency Pinning and Upgrade Policy

## Requirement sets

- `requirements-app.txt` — FastAPI, Streamlit, LangGraph, persistence and optional OpenAI/Anthropic provider integrations.
- `requirements-mcp.txt` — smaller MCP simulation-server runtime.
- `requirements-dev.txt` — pytest, coverage, Ruff and mypy for engineering checks.
- `requirements.txt` — convenience include for the application runtime.

Every direct requirement is exactly pinned with `==`. The app and MCP Dockerfiles install different sets to reduce the MCP image footprint.

## Verification

`scripts/check_framework_imports.py` performs two checks in the Docker test image:

1. Parse `requirements-app.txt` and `requirements-dev.txt`; reject any direct dependency that is not exactly pinned.
2. Compare every installed distribution version with its declared pin, then import the required Streamlit, LangChain, LangGraph, PostgreSQL-checkpointer and MCP surfaces.

It also compiles and runs a small LangGraph checkpointed graph. `scripts/check_mcp_service_versions.py` compares the running purpose-specific MCP image against `requirements-mcp.txt`. Separate scripts test human interrupt/resume, Streamlit startup and PostgreSQL restart recovery.

## Upgrade rule

Do not update one framework opportunistically. Use a dependency-upgrade change that:

1. updates the requirement files and `pyproject.toml` together;
2. updates `PACKAGE_VERSIONS.md`;
3. builds both Docker images without cached package layers;
4. runs `scripts/verify_docker.sh` or its PowerShell equivalent;
5. confirms the strict MCP profile, Streamlit APIs, LangGraph interrupt behavior and PostgreSQL checkpointer still work;
6. records any schema or serialized-state migration requirement.

LangGraph, Streamlit, MCP and provider integrations are version-sensitive. An exact pin proves reproducibility, not perpetual compatibility.
