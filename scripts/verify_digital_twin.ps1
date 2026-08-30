$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH="$PWD\src"
python -c "import sys; assert sys.version_info[:3] == (3,14,7), f'Python 3.14.7 is required, got {sys.version.split()[0]}'"
python -m compileall -q src
coverage erase
coverage run -m pytest
coverage report --fail-under=80
Remove-Item -Recurse -Force .verify-data -ErrorAction SilentlyContinue
python -m lpr_cpe_demo.digital_twin.cli generate --profile smoke --data-root .verify-data | Out-File -Encoding utf8 "$env:TEMP\lpr_dt_smoke.json"
python -c "import json,pathlib; p=list(pathlib.Path('.verify-data').glob('RUN-*/catalog.json')); assert len(p)==1; c=json.loads(p[0].read_text()); assert c['quality']['passed']; assert c['dataset_count']==20; print('smoke quality PASS',c['run_id'])"
