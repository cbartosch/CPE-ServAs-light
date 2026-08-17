#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python scripts/check_environment.py 2>/dev/null || true
docker compose up --build -d --wait --wait-timeout 300
docker compose ps
if command -v python >/dev/null 2>&1; then
  python scripts/smoke_test.py
fi
printf '\nStreamlit: http://localhost:8501\nFastAPI:   http://localhost:8000/docs\nMCP:       http://localhost:8100/health\n'
printf 'Use ./scripts/verify_docker.sh for a full build, health, and test cycle.\n'
