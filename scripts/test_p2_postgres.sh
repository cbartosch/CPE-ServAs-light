#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose up -d postgres
docker compose --profile postgres-test build p2-postgres-test
docker compose --profile postgres-test run --rm p2-postgres-test
