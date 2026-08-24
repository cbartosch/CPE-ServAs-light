$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker version | Out-Null
docker compose version | Out-Null
if (-not (Test-Path ".env.digital-twin")) { Copy-Item .env.digital-twin.example .env.digital-twin }
docker compose --env-file .env.digital-twin -f docker-compose.digital-twin.yml build
docker compose --env-file .env.digital-twin -f docker-compose.digital-twin.yml up -d
Start-Sleep -Seconds 4
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/health | Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8502/_stcore/health | Select-Object -ExpandProperty Content
