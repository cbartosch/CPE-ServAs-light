<#
    Capture the certificate chain the network presents for PyPI and stage it for
    the Docker build. Closes the gap that scripts\stage-ca.ps1 requires a .crt
    file you must already have exported by hand.

        .\scripts\capture-ca.ps1
        docker compose build --no-cache

    Only CA certificates are written; the pypi.org leaf is skipped.
#>
param([string]$TestHost = "pypi.org", [int]$Port = 443)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $repoRoot "docker\certs"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$client = New-Object System.Net.Sockets.TcpClient($TestHost, $Port)
$cb = [System.Net.Security.RemoteCertificateValidationCallback] { param($s, $c, $ch, $e) $true }
$ssl = New-Object System.Net.Security.SslStream($client.GetStream(), $false, $cb)
try {
    $ssl.AuthenticateAsClient($TestHost)
    $leaf = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
    Write-Host "Chain presented for ${TestHost}:"
    Write-Host "  leaf issuer: $($leaf.Issuer)"

    $chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
    $chain.ChainPolicy.RevocationMode = "NoCheck"
    [void]$chain.Build($leaf)

    $written = 0
    foreach ($element in $chain.ChainElements) {
        $cert = $element.Certificate
        $basic = $cert.Extensions | Where-Object {
            $_ -is [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]
        } | Select-Object -First 1
        if ($null -eq $basic -or -not $basic.CertificateAuthority) { continue }

        $sha = [System.Security.Cryptography.SHA256]::Create()
        try { $fp = ($sha.ComputeHash($cert.RawData) | ForEach-Object { $_.ToString("x2") }) -join "" }
        finally { $sha.Dispose() }

        $name = "captured-ca-$($fp.Substring(0,16)).crt"
        $pem = "-----BEGIN CERTIFICATE-----`n" +
               [Convert]::ToBase64String($cert.RawData, "InsertLineBreaks").Replace("`r`n", "`n") +
               "`n-----END CERTIFICATE-----`n"
        [System.IO.File]::WriteAllText((Join-Path $outDir $name), $pem)
        Write-Host "  staged $name  <- $($cert.Subject)"
        $written++
    }
    if ($written -eq 0) { throw "No CA certificates found in the presented chain." }
    Write-Host ""
    Write-Host "Staged $written CA certificate(s). Rebuild with: docker compose build --no-cache"
} finally {
    $ssl.Dispose(); $client.Dispose()
}
