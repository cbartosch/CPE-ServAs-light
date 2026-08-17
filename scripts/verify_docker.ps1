$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
try {
    try {
        python scripts/preflight.py
    }
    catch {
        Write-Warning "Local Python preflight skipped."
    }

    docker compose up --build -d --wait --wait-timeout 300
    docker compose --profile test build test

    docker compose --profile test run --rm `
      -e API_HEALTH_URL=http://api:8000/health `
      -e MCP_HEALTH_URL=http://mcp-sim:8100/health `
      -e UI_HEALTH_URL=http://ui:8501/_stcore/health `
      test python scripts/smoke_test.py

    docker compose --profile test run --rm `
      -e API_URL=http://api:8000 `
      test python scripts/api_workflow_smoke.py

    docker compose --profile test run --rm `
      -e MCP_HEALTH_URL=http://mcp-sim:8100/health `
      test python scripts/check_mcp_service_versions.py

    docker compose --profile test run --rm test python scripts/check_postgres_resume.py
    docker compose --profile test run --rm test
    Write-Host "`nFull Docker verification: PASS"
}
finally {
    docker compose down
}
