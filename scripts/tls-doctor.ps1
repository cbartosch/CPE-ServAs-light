param(
    [string]$TestHost = "pypi.org",
    [string]$TestUrl = "https://pypi.org/simple/"
)

$ErrorActionPreference = "Continue"
$failures = 0
function Pass([string]$Message) { Write-Host "PASS  $Message" -ForegroundColor Green }
function Warn([string]$Message) { Write-Host "WARN  $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { Write-Host "FAIL  $Message" -ForegroundColor Red; $script:failures++ }

Write-Host "TLS doctor for $TestUrl`n"

if (Get-Command docker -ErrorAction SilentlyContinue) {
    Pass ((docker --version) -join " ")
    try { Pass ((docker compose version) -join " ") } catch { Fail "Docker Compose is unavailable" }
}
else { Fail "Docker is not installed or not on PATH" }

$proxyNames = @("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY") | Where-Object { [Environment]::GetEnvironmentVariable($_) }
if ($proxyNames.Count -gt 0) { Pass "Proxy environment present: $($proxyNames -join ', ') (values redacted)" }
else { Warn "No proxy environment variables are set" }

try {
    [System.Net.Dns]::GetHostAddresses($TestHost) | Out-Null
    Pass "DNS resolves $TestHost"
}
catch { Fail "DNS cannot resolve $TestHost; this is not a certificate error" }

try {
    $response = Invoke-WebRequest -Uri $TestUrl -Method Head -TimeoutSec 15 -UseBasicParsing
    Pass "PowerShell verifies HTTPS (status $($response.StatusCode))"
}
catch {
    $message = $_.Exception.Message
    if ($message -match "certificate|SSL|TLS") { Fail "TLS verification failed: $message" }
    elseif ($message -match "proxy|CONNECT") { Fail "Proxy connection failed: $message" }
    else { Fail "HTTPS request failed: $message" }
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$certDir = Join-Path $repoRoot "docker\certs"
$certFiles = @(Get-ChildItem -LiteralPath $certDir -Filter *.crt -File -ErrorAction SilentlyContinue)
if ($certFiles.Count -eq 0) {
    Warn "No corporate CA is staged in docker/certs"
}
else {
    foreach ($file in $certFiles) {
        try {
            $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($file.FullName)
            $basic = $cert.Extensions | Where-Object {
                $_ -is [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]
            } | Select-Object -First 1
            if ($null -eq $basic -or -not $basic.CertificateAuthority) {
                Fail "$($file.Name) is not a CA certificate"
            }
            else { Pass "$($file.Name) is a valid CA certificate" }
        }
        catch { Fail "$($file.Name) is not a valid X.509 certificate: $($_.Exception.Message)" }
    }
}

if ($failures -gt 0) {
    Write-Host "`nFix DNS or proxy failures before treating the problem as a CA-chain issue." -ForegroundColor Yellow
    exit 1
}
Write-Host "`nTLS doctor completed without failures."
