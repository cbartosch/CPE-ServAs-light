#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
python -c "import sys; assert sys.version_info[:3] == (3,14,2), f'Python 3.14.2 is required, got {sys.version.split()[0]}'"
python -m compileall -q src
coverage erase
coverage run -m pytest
coverage report --fail-under=80
rm -rf .verify-data
python -m lpr_cpe_demo.digital_twin.cli generate --profile smoke --data-root .verify-data > /tmp/lpr_dt_smoke.json
python - <<'PY'
import json
from pathlib import Path
cat_files=list(Path('.verify-data').glob('RUN-*/catalog.json'))
assert len(cat_files)==1
cat=json.loads(cat_files[0].read_text())
assert cat['quality']['passed'] is True
assert cat['dataset_count']==16
print('smoke quality PASS',cat['run_id'])
PY
