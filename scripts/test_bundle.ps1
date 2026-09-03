$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

docker compose --profile test build test
if ($LASTEXITCODE -ne 0) {
    throw "Containerized application test image failed to build."
}

docker compose --profile test run --rm test
if ($LASTEXITCODE -ne 0) {
    throw "Containerized application test profile failed."
}

& (Join-Path $PSScriptRoot "test_p2_postgres.ps1")
