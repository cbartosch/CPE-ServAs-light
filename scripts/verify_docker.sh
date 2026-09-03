#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "Docker Engine not available" >&2; exit 2; }
docker compose version >/dev/null
[[ -f .env ]] || cp .env.example .env

workflow_token="$({
  sed -n 's/^WORKFLOW_INTERNAL_TOKEN=//p' .env | tail -n 1
} || true)"
if [[ -z "$workflow_token" ]]; then
  workflow_token="$(python -c 'import secrets; print(secrets.token_hex(32))')"
  WORKFLOW_TOKEN="$workflow_token" python - <<'PY'
import os
from pathlib import Path

path = Path(".env")
token = os.environ["WORKFLOW_TOKEN"]
text = path.read_text(encoding="utf-8")
line = f"WORKFLOW_INTERNAL_TOKEN={token}"
if "WORKFLOW_INTERNAL_TOKEN=" in text:
    text = "\n".join(
        line if item.startswith("WORKFLOW_INTERNAL_TOKEN=") else item
        for item in text.splitlines()
    ) + "\n"
else:
    text += f"\n{line}\n"
path.write_text(text, encoding="utf-8")
PY
  echo "Generated a local workflow mutation token in .env."
fi

docker compose build
docker compose up -d
sleep 6
curl -fsS http://127.0.0.1:${MCP_PORT:-8100}/health
curl -fsS http://127.0.0.1:${API_PORT:-8000}/health
curl -fsS http://127.0.0.1:${DT_API_PORT:-8001}/health
curl -fsS http://127.0.0.1:${UI_PORT:-8501}/_stcore/health
python scripts/post_action_quarantine_smoke.py \
  --workflow-url "http://127.0.0.1:${API_PORT:-8000}" \
  --internal-token "$workflow_token"
echo
echo "Unified stack PASS: UI ${UI_PORT:-8501}; APIs ${API_PORT:-8000}/${DT_API_PORT:-8001}; MCP ${MCP_PORT:-8100}; protected P2 smoke"
