#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'TXT'
Usage: scripts/stage-ca.sh /path/to/corporate-root.crt

Stages one or more PEM/DER CA certificates into docker/certs/, one certificate
per .crt file. Only certificates with Basic Constraints CA:TRUE are accepted.
TXT
}

[[ $# -eq 1 ]] || { usage >&2; exit 2; }
src=$1
[[ -f "$src" ]] || { echo "CA file not found: $src" >&2; exit 2; }
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 2; }

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out_dir="$repo_root/docker/certs"
mkdir -p "$out_dir"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

pem="$tmp/input.pem"
if grep -q 'BEGIN CERTIFICATE' "$src" 2>/dev/null; then
  cp "$src" "$pem"
else
  if ! openssl x509 -inform DER -in "$src" -out "$pem" 2>/dev/null; then
    echo "Not a PEM or DER X.509 certificate: $src" >&2
    exit 2
  fi
fi

# Debian update-ca-certificates requires one certificate per .crt file.
awk -v d="$tmp" '
  /-----BEGIN CERTIFICATE-----/ {n++; f=sprintf("%s/cert-%03d.pem", d, n)}
  n {print > f}
  /-----END CERTIFICATE-----/ {close(f)}
' "$pem"

count=0
for cert in "$tmp"/cert-*.pem; do
  [[ -e "$cert" ]] || continue
  if ! openssl x509 -in "$cert" -noout >/dev/null 2>&1; then
    echo "Skipping malformed certificate: $cert" >&2
    continue
  fi
  if ! openssl x509 -in "$cert" -noout -text | grep -A1 'Basic Constraints' | grep -q 'CA:TRUE'; then
    subject=$(openssl x509 -in "$cert" -noout -subject | sed 's/^subject=//')
    echo "Skipping non-CA certificate:$subject" >&2
    continue
  fi

  fingerprint=$(openssl x509 -in "$cert" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':' | tr '[:upper:]' '[:lower:]')
  short=${fingerprint:0:16}
  dst="$out_dir/corporate-ca-$short.crt"
  openssl x509 -in "$cert" -out "$dst"
  chmod 0644 "$dst"
  subject=$(openssl x509 -in "$dst" -noout -subject | sed 's/^subject=//')
  issuer=$(openssl x509 -in "$dst" -noout -issuer | sed 's/^issuer=//')
  echo "staged: $(basename "$dst")"
  echo "  subject:$subject"
  echo "  issuer: $issuer"
  count=$((count + 1))
done

if [[ $count -eq 0 ]]; then
  echo "No CA certificates were staged. Export the corporate ROOT/issuing CA, not the website leaf certificate." >&2
  exit 1
fi

echo "Staged $count CA certificate(s) in docker/certs/."
echo "Rebuild with: docker compose build --no-cache"
