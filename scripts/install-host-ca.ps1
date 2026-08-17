param(
    [Parameter(Mandatory = $true)]
    [string]$CaFile
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $CaFile -PathType Leaf)) {
    throw "CA file not found: $CaFile"
}
$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($CaFile)
$basic = $cert.Extensions | Where-Object {
    $_ -is [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]
} | Select-Object -First 1
if ($null -eq $basic -or -not $basic.CertificateAuthority) {
    throw "Refusing to trust a non-CA certificate. Export the corporate root or issuing CA."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session."
}

$store = [System.Security.Cryptography.X509Certificates.X509Store]::new("Root", "LocalMachine")
try {
    $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $store.Add($cert)
}
finally {
    $store.Close()
}
Write-Host "Installed CA in LocalMachine\Root. Re-run scripts\tls-doctor.ps1."
