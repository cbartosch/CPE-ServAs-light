param(
    [Parameter(Mandatory = $true)]
    [string]$CaFile
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $CaFile -PathType Leaf)) {
    throw "CA file not found: $CaFile"
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $repoRoot "docker\certs"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($CaFile)
$basic = $cert.Extensions | Where-Object {
    $_ -is [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]
} | Select-Object -First 1
if ($null -eq $basic -or -not $basic.CertificateAuthority) {
    throw "Refusing to stage a non-CA certificate. Export the corporate root or issuing CA."
}

$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $fingerprint = ($sha.ComputeHash($cert.RawData) | ForEach-Object { $_.ToString("x2") }) -join ""
}
finally {
    $sha.Dispose()
}
$name = "corporate-ca-$($fingerprint.Substring(0,16)).crt"
$destination = Join-Path $outDir $name
$pemBody = [Convert]::ToBase64String($cert.RawData, [Base64FormattingOptions]::InsertLineBreaks)
@("-----BEGIN CERTIFICATE-----", $pemBody, "-----END CERTIFICATE-----", "") |
    Set-Content -LiteralPath $destination -Encoding ascii

Write-Host "Staged $name"
Write-Host "  Subject: $($cert.Subject)"
Write-Host "  Issuer:  $($cert.Issuer)"
Write-Host "Rebuild with: docker compose build --no-cache"
