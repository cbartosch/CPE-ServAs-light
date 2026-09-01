$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".env")) {
    if (-not (Test-Path ".env.example")) { throw "Missing .env and .env.example" }
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example. Review passwords before shared use." -ForegroundColor Yellow
}

docker compose up --build --force-recreate -d --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) { throw "Docker Compose startup failed." }

docker compose exec -T ui python scripts/runtime_smoke.py
if ($LASTEXITCODE -ne 0) { throw "UI runtime connectivity smoke failed." }

Write-Host "Unified Streamlit: http://127.0.0.1:8501"
Write-Host "Main API docs:     http://127.0.0.1:8000/docs"
Write-Host "Digital Twin API:  http://127.0.0.1:8001/docs"
