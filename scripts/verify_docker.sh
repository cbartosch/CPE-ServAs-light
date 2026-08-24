#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "Docker Engine not available" >&2; exit 2; }
docker compose version >/dev/null
[[ -f .env.digital-twin ]] || cp .env.digital-twin.example .env.digital-twin
docker compose --env-file .env.digital-twin -f docker-compose.digital-twin.yml build
docker compose --env-file .env.digital-twin -f docker-compose.digital-twin.yml up -d
sleep 4
curl -fsS http://127.0.0.1:${DT_API_PORT:-8001}/health
a=$(curl -fsS http://127.0.0.1:${DT_UI_PORT:-8502}/_stcore/health)
echo "$a"
