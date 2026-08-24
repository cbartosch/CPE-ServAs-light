$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".env.digital-twin")) { throw "Missing .env.digital-twin. Copy .env.digital-twin.example and change DT_PASSWORD." }
docker compose --env-file .env.digital-twin -f docker-compose.digital-twin.yml up --build -d
Write-Host "Streamlit: http://127.0.0.1:8502"
Write-Host "API docs:  http://127.0.0.1:8001/docs"
