#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose --profile test build test
docker compose --profile test run --rm test
./scripts/test_p2_postgres.sh
