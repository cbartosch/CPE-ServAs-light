#!/usr/bin/env bash
# Download linux wheels on the host so the Docker build needs no network.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
ARCH="${VENDOR_ARCH:-$(uname -m | sed 's/^arm64$/aarch64/')}"
mkdir -p vendor
echo "downloading manylinux2014_${ARCH} wheels for python 3.12"
python3 -m pip download --dest vendor \
  --platform "manylinux2014_${ARCH}" \
  --python-version 3.12 --implementation cp --only-binary=:all: \
  -r requirements-app.txt -r requirements-mcp.txt -r requirements-dev.txt
echo "vendored $(ls vendor/*.whl 2>/dev/null | wc -l | tr -d ' ') wheels for ${ARCH}"
echo "rebuild with: docker compose build --no-cache"
