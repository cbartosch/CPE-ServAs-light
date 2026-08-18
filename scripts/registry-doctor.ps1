<#
    Diagnose why the Docker daemon cannot pull a base image.

        .\scripts\registry-doctor.ps1

    This is a DIFFERENT failure from pip failing inside a build. The daemon fetches
    the image manifest before any layer exists, so a CA staged into docker/certs/
    is never reached. Fixing it means fixing the daemon's trust or avoiding the
    public registry.
#>
param([string]$Image = "python:3.12-slim",
      [string]$Registry = "registry-1.docker.io")

$ErrorActionPreference = "Continue"
function Pass($m) { Write-Host "PASS  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "WARN  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "FAIL  $m" -ForegroundColor Red }

Write-Host "Registry doctor`n"

# 1. Is the image already local? If so, the build needs no pull at all.
$local = docker images --format "{{.Repository}}:{{.Tag}}" 2>$null |
         Where-Object { $_ -eq $Image }
if ($local) {
    Pass "$Image is already present locally"
    Write-Host "      Build with --pull=never and the registry is never contacted:"
    Write-Host "      docker compose build --pull never"
} else {
    Warn "$Image is not present locally, so the build must pull it"
}

# 2. What certificate chain does the registry present to THIS host?
Write-Host "`nChain presented for ${Registry}:443"
try {
    $client = New-Object System.Net.Sockets.TcpClient($Registry, 443)
    $cb = [System.Net.Security.RemoteCertificateValidationCallback] { param($s,$c,$ch,$e) $true }
    $ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false, $cb)
    $ssl.AuthenticateAsClient($Registry)
    $leaf = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
    Write-Host "      leaf issuer : $($leaf.Issuer)"
    $chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
    $chain.ChainPolicy.RevocationMode = "NoCheck"
    $built = $chain.Build($leaf)
    $root = $chain.ChainElements[$chain.ChainElements.Count-1].Certificate
    Write-Host "      root        : $($root.Subject)"
    if ($root.Subject -match "Docker|DigiCert|Amazon|Google|ISRG|Baltimore") {
        Pass "the chain terminates at a public root, so no interception on this port"
        Warn "if the pull still fails, the daemon is not using this host's trust store"
    } else {
        Fail "the chain terminates at a private root: TLS is being intercepted"
        Write-Host "      $($root.Subject)"
        Write-Host "      The daemon must trust this root, or you must avoid the registry."
    }
    if (-not $built) { Warn "this host cannot validate the chain either" }
    $ssl.Dispose(); $client.Dispose()
} catch {
    Fail "cannot reach ${Registry}:443 at all: $_"
    Write-Host "      The registry is blocked, not intercepted. An internal mirror is"
    Write-Host "      the only route."
}

# 3. Is the root in the machine store, where Docker Desktop looks?
Write-Host "`nTrusted roots on this host"
$roots = Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue
$private = $roots | Where-Object { $_.Subject -notmatch "DigiCert|Baltimore|GlobalSign|Microsoft|VeriSign|Thawte|Entrust|COMODO|USERTrust|AddTrust|Go Daddy|Amazon|ISRG|Starfield|SecureTrust|Certum|QuoVadis|D-TRUST|Sectigo" }
Write-Host "      $($roots.Count) root(s) in LocalMachine\Root, $($private.Count) look private:"
$private | Select-Object -First 5 | ForEach-Object { Write-Host "        $($_.Subject)" }
if ($private.Count -eq 0) {
    Fail "no private root in LocalMachine\Root"
    Write-Host "      A cert in CurrentUser\Root is NOT enough: Docker Desktop reads the"
    Write-Host "      machine store. Import it there and restart Docker Desktop."
}

Write-Host @"

WHAT TO DO, in order of reliability

1. Internal mirror. Avoids the registry entirely and needs no certificate work.
     BASE_IMAGE=artifactory.example.com/docker-remote/python:3.12-slim
   Set it in .env, then: docker compose build

2. Already-local image. Pull the image on any machine that can, then:
     docker save python:3.12-slim -o python-312-slim.tar
     docker load -i python-312-slim.tar
     docker compose build --pull never

3. Trust the root in the daemon. Import the corporate root into
   LocalMachine\Trusted Root Certification Authorities, then restart Docker
   Desktop completely, not just the window. Docker Desktop reads the MACHINE
   store; a cert in the user store will not be seen.

Note: scripts\capture-ca.ps1 stages a CA for pip INSIDE the build. It cannot help
here, because this failure happens before any build layer exists.
"@
