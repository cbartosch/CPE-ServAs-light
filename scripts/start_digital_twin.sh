#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env.digital-twin ]]; then
  echo "Missing .env.digital-twin. Copy .env.digital-twin.example and change DT_PASSWORD." >&2
  exit 2
fi
docker compose --env-file .env.digital-twin -f docker-compose.digital-twin.yml up --build -d
echo "Streamlit: http://127.0.0.1:${DT_UI_PORT:-8502}"
echo "API docs:  http://127.0.0.1:${DT_API_PORT:-8001}/docs"
