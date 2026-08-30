[CmdletBinding()]
param(
    [ValidateRange(1, 500000)] [int] $Homes = 500,
    [string] $Profile = "smoke",
    [ValidateRange(0, 2147483647)] [int] $Seed = 2401,
    [string] $RunDate = (Get-Date -Format "yyyy-MM-dd"),
    [string] $BaseUrl = "http://127.0.0.1:8001"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

& $python `
  (Join-Path $PSScriptRoot "repair_current_schema_run.py") `
  --base-url $BaseUrl `
  --env-file (Join-Path $repo ".env") `
  --homes $Homes `
  --profile $Profile `
  --seed $Seed `
  --run-date $RunDate

if ($LASTEXITCODE -ne 0) {
    throw "Current-schema run recovery failed with exit code $LASTEXITCODE."
}
