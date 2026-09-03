$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

docker version | Out-Null
docker compose version | Out-Null

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
}

$envContent = Get-Content -LiteralPath ".env" -Raw
$tokenMatch = [regex]::Match(
    $envContent,
    '(?m)^WORKFLOW_INTERNAL_TOKEN=(.*)$'
)
$workflowToken = if ($tokenMatch.Success) {
    $tokenMatch.Groups[1].Value.Trim()
} else {
    ""
}
if (-not $workflowToken) {
    $workflowToken = [Convert]::ToHexString(
        [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    ).ToLowerInvariant()
    if ($tokenMatch.Success) {
        $envContent = [regex]::Replace(
            $envContent,
            '(?m)^WORKFLOW_INTERNAL_TOKEN=.*$',
            "WORKFLOW_INTERNAL_TOKEN=$workflowToken",
            1
        )
    } else {
        $envContent += "`nWORKFLOW_INTERNAL_TOKEN=$workflowToken`n"
    }
    [System.IO.File]::WriteAllText(
        (Join-Path (Get-Location) ".env"),
        $envContent,
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host "Generated a local workflow mutation token in .env."
}

docker compose build
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose build failed."
}

docker compose up -d
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose startup failed."
}

Start-Sleep -Seconds 6
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8100/health |
    Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health |
    Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8001/health |
    Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8501/_stcore/health |
    Select-Object -ExpandProperty Content

& python scripts/post_action_quarantine_smoke.py `
    --workflow-url http://127.0.0.1:8000 `
    --internal-token $workflowToken
if ($LASTEXITCODE -ne 0) {
    throw "Protected P2 runtime smoke failed."
}

Write-Host `
    "Unified stack PASS: UI 8501; APIs 8000/8001; MCP 8100; protected P2 smoke" `
    -ForegroundColor Green
