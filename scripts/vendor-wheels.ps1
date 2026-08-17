<#
    Download linux wheels on the host so the Docker build needs no network.

        .\scripts\vendor-wheels.ps1
        docker compose build --no-cache
#>
param([string]$Arch)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

if (-not $Arch) {
    $Arch = "x86_64"
    try {
        $a = docker info --format '{{.Architecture}}' 2>$null
        if ($a -match 'aarch64|arm64') { $Arch = "aarch64" }
    } catch {
        if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { $Arch = "aarch64" }
    }
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "python not found on PATH." -ForegroundColor Red
    Write-Host "Install Python 3.12, or run pip download on any machine with index"
    Write-Host "access and copy the .whl files into .\vendor\"
    exit 1
}

New-Item -ItemType Directory -Path vendor -Force | Out-Null
Write-Host "downloading manylinux2014_$Arch wheels for python 3.12"
python -m pip download --dest vendor `
    --platform "manylinux2014_$Arch" `
    --python-version 3.12 --implementation cp --only-binary=:all: `
    -r requirements-app.txt -r requirements-mcp.txt -r requirements-dev.txt

$n = (Get-ChildItem vendor -Filter *.whl -ErrorAction SilentlyContinue).Count
Write-Host "vendored $n wheels for $Arch" -ForegroundColor Green
Write-Host "rebuild with: docker compose build --no-cache"
