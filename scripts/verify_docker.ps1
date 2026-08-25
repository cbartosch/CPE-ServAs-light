$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker version | Out-Null
docker compose version | Out-Null
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }
docker compose build
docker compose up -d
Start-Sleep -Seconds 6
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8100/health | Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health | Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/health | Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health | Select-Object -ExpandProperty Content
Write-Host "Unified stack PASS: UI 8501; APIs 8000/8001; MCP 8100" -ForegroundColor Green
