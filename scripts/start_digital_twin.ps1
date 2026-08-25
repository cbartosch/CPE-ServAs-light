$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".env")) {
    if (-not (Test-Path ".env.example")) { throw "Missing .env and .env.example" }
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example. Review passwords before shared use." -ForegroundColor Yellow
}
docker compose up --build -d
Write-Host "Unified Streamlit: http://127.0.0.1:8501"
Write-Host "Main API docs:     http://127.0.0.1:8000/docs"
Write-Host "Digital Twin API:  http://127.0.0.1:8001/docs"
