#!/usr/bin/env bash
# Diagnose why the Docker daemon cannot pull a base image.
#
# Different from pip failing inside a build: the daemon fetches the manifest before
# any layer exists, so a CA staged into docker/certs/ is never reached.
set -uo pipefail
IMAGE="${1:-python:3.12-slim}"
REGISTRY="${2:-registry-1.docker.io}"

echo "Registry doctor"
echo
if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -qx "$IMAGE"; then
  echo "PASS  $IMAGE is already local; build with --pull never"
else
  echo "WARN  $IMAGE is not local, so the build must pull it"
fi

echo
echo "Chain presented for $REGISTRY:443"
if command -v openssl >/dev/null; then
  chain=$(openssl s_client -showcerts -connect "$REGISTRY:443" \
          -servername "$REGISTRY" </dev/null 2>/dev/null)
  root=$(printf '%s' "$chain" | grep -m1 "^ *[0-9] s:" | tail -1)
  printf '%s' "$chain" | grep -E "^ *[0-9] s:" | sed 's/^/      /'
  if printf '%s' "$chain" | grep -qiE "zscaler|bluecoat|forcepoint|palo alto|netskope|corporate|internal"; then
    echo "FAIL  a private root appears in the chain: TLS is being intercepted"
  fi
else
  echo "WARN  openssl not available"
fi

cat <<'EOF'

WHAT TO DO, in order of reliability

1. Internal mirror, which avoids the registry and needs no certificate work:
     BASE_IMAGE=artifactory.example.com/docker-remote/python:3.12-slim
2. Load the image from a tar built on a machine that can pull:
     docker save python:3.12-slim -o python.tar && docker load -i python.tar
     docker compose build --pull never
3. Trust the corporate root in the daemon's own store and restart the daemon.

scripts/capture-ca.* stages a CA for pip INSIDE the build. It cannot help here.
EOF
