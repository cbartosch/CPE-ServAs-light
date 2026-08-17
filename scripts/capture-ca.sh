#!/usr/bin/env bash
# Capture the CA chain the network presents for PyPI and stage it for the build.
# Closes the gap that scripts/stage-ca.sh needs a .crt you already exported.
set -euo pipefail

HOST="${1:-pypi.org}"
PORT="${2:-443}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/docker/certs"
mkdir -p "$OUT"

command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
openssl s_client -showcerts -connect "$HOST:$PORT" -servername "$HOST" </dev/null 2>/dev/null \
  | awk '/BEGIN CERT/,/END CERT/' > "$tmp/chain.pem"
[ -s "$tmp/chain.pem" ] || { echo "could not reach $HOST:$PORT" >&2; exit 1; }

csplit -sz -f "$tmp/cert-" -b '%02d.pem' "$tmp/chain.pem" '/BEGIN CERTIFICATE/' '{*}'

written=0
for cert in "$tmp"/cert-*.pem; do
  if openssl x509 -in "$cert" -noout -text | grep -q "CA:TRUE"; then
    fp="$(openssl x509 -in "$cert" -noout -fingerprint -sha256 \
          | tr -d ':' | cut -d= -f2 | tr 'A-F' 'a-f' | cut -c1-16)"
    dest="$OUT/captured-ca-$fp.crt"
    cp "$cert" "$dest"
    echo "  staged $(basename "$dest")  <- $(openssl x509 -in "$cert" -noout -subject)"
    written=$((written + 1))
  fi
done

[ "$written" -gt 0 ] || { echo "no CA certificates in the presented chain" >&2; exit 1; }
echo
echo "Staged $written CA certificate(s). Rebuild with: docker compose build --no-cache"
