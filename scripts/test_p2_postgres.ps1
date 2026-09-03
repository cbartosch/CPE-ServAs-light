$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

docker compose up -d postgres
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL service did not start."
}

docker compose --profile postgres-test build p2-postgres-test
if ($LASTEXITCODE -ne 0) {
    throw "P2 PostgreSQL test image failed to build."
}

docker compose --profile postgres-test run --rm p2-postgres-test
if ($LASTEXITCODE -ne 0) {
    throw "P2 PostgreSQL reliability tests failed."
}
