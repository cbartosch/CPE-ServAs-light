$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

try {
    python scripts/check_environment.py
}
catch {
    Write-Warning "Python environment check skipped."
}

docker compose up --build --force-recreate -d --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) { throw "Docker Compose startup failed." }

docker compose ps

docker compose exec -T ui python scripts/runtime_smoke.py
if ($LASTEXITCODE -ne 0) { throw "UI runtime connectivity smoke failed." }

Write-Host ""
Write-Host "Streamlit:       http://localhost:8501"
Write-Host "FastAPI:         http://localhost:8000/docs"
Write-Host "Digital Twin:    http://localhost:8001/docs"
Write-Host "MCP:             http://localhost:8100/health"
Write-Host "Application image and API routing verified." -ForegroundColor Green
