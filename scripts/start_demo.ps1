$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
try { python scripts/check_environment.py } catch { Write-Warning "Python environment check skipped." }
docker compose up --build -d --wait --wait-timeout 300
docker compose ps
try { python scripts/smoke_test.py } catch { Write-Warning "Local Python smoke test skipped; Docker health checks passed." }
Write-Host ""
Write-Host "Streamlit: http://localhost:8501"
Write-Host "FastAPI:   http://localhost:8000/docs"
Write-Host "MCP:       http://localhost:8100/health"
Write-Host "Use .\scripts\verify_docker.ps1 for a full build, health, and test cycle."
