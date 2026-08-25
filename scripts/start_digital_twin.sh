#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || { echo "Missing .env and .env.example" >&2; exit 2; }
  cp .env.example .env
  echo "Created .env from .env.example. Review passwords before shared use." >&2
fi
docker compose up --build -d
echo "Unified Streamlit: http://127.0.0.1:${UI_PORT:-8501}"
echo "Main API docs:     http://127.0.0.1:${API_PORT:-8000}/docs"
echo "Digital Twin API:  http://127.0.0.1:${DT_API_PORT:-8001}/docs"
