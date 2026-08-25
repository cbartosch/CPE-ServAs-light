#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "Docker Engine not available" >&2; exit 2; }
docker compose version >/dev/null
[[ -f .env ]] || cp .env.example .env
docker compose build
docker compose up -d
sleep 6
curl -fsS http://127.0.0.1:${MCP_PORT:-8100}/health
curl -fsS http://127.0.0.1:${API_PORT:-8000}/health
curl -fsS http://127.0.0.1:${DT_API_PORT:-8001}/health
curl -fsS http://127.0.0.1:${UI_PORT:-8501}/_stcore/health
echo
echo "Unified stack PASS: UI ${UI_PORT:-8501}; APIs ${API_PORT:-8000}/${DT_API_PORT:-8001}; MCP ${MCP_PORT:-8100}"
