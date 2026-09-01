#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python scripts/check_environment.py 2>/dev/null || true
docker compose up --build --force-recreate -d --wait --wait-timeout 300
docker compose ps
docker compose exec -T ui python scripts/runtime_smoke.py
printf '\nStreamlit:       http://localhost:8501\n'
printf 'FastAPI:         http://localhost:8000/docs\n'
printf 'Digital Twin:    http://localhost:8001/docs\n'
printf 'MCP:             http://localhost:8100/health\n'
printf 'Application image and API routing verified.\n'
