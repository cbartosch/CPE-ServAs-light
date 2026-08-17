#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 ]] || { echo "Usage: $0 /path/to/corporate-root.crt" >&2; exit 2; }
src=$1
[[ -f "$src" ]] || { echo "CA file not found: $src" >&2; exit 2; }
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 2; }

# Require a real CA certificate. Do not add a website leaf certificate as a trust anchor.
if ! openssl x509 -in "$src" -noout >/dev/null 2>&1; then
  echo "The host installer expects PEM. Convert DER first: openssl x509 -inform DER -in input.cer -out corporate-root.crt" >&2
  exit 2
fi
if ! openssl x509 -in "$src" -noout -text | grep -A1 'Basic Constraints' | grep -q 'CA:TRUE'; then
  echo "Refusing to trust a non-CA certificate. Export the corporate root/issuing CA." >&2
  exit 2
fi

case "$(uname -s)" in
  Linux)
    command -v update-ca-certificates >/dev/null || { echo "update-ca-certificates is unavailable" >&2; exit 2; }
    name="corporate-$(openssl x509 -in "$src" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':' | cut -c1-16).crt"
    sudo install -m 0644 "$src" "/usr/local/share/ca-certificates/$name"
    sudo update-ca-certificates
    ;;
  Darwin)
    sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$src"
    ;;
  *)
    echo "Unsupported OS: $(uname -s). On Windows, run an elevated PowerShell and use certutil -addstore -f Root <certificate>." >&2
    exit 2
    ;;
esac

echo "Host trust store updated. Re-run: make doctor"
