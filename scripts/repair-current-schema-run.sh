#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PYTHON=${PYTHON:-python}
exec "$PYTHON" "$SCRIPT_DIR/repair_current_schema_run.py" \
  --env-file "$REPO/.env" "$@"
