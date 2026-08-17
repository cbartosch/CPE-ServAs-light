.PHONY: help env up down reset logs test smoke validate verify clean doctor certs host-certs

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

env: ## create .env from the safe template when absent
	@test -f .env || cp .env.example .env && echo ".env ready"

up: env ## build and start the Docker Desktop stack
	docker compose up --build -d --wait --wait-timeout 300

down: ## stop the stack
	docker compose down

reset: ## stop the stack and remove demo data volumes
	docker compose down -v

logs: ## follow service logs
	docker compose logs -f --tail=200

test: ## build and run the complete container test gate
	docker compose --profile test build test
	docker compose --profile test run --rm test

smoke: ## run the local portable smoke test
	python scripts/smoke_test.py

validate: ## run local source, scenario and test validation
	python scripts/validate_compose.py
	PYTHONPATH=src python -m compileall -q src tests scripts
	PYTHONPATH=src python scripts/run_scenario_matrix.py
	PYTHONPATH=src python -m pytest -q --cov=lpr_cpe_demo --cov-report=term-missing

verify: ## build, start and exercise the live Docker stack
	./scripts/verify_docker.sh

doctor: ## distinguish Docker, DNS, proxy and TLS/CA problems
	./scripts/tls-doctor.sh

certs: ## stage a corporate CA: make certs CA_FILE=/path/root.crt
	@test -n "$(CA_FILE)" || { echo "usage: make certs CA_FILE=/path/to/corporate-root.crt" >&2; exit 2; }
	./scripts/stage-ca.sh "$(CA_FILE)"

host-certs: ## install a corporate CA in the host trust store; requires sudo
	@test -n "$(CA_FILE)" || { echo "usage: make host-certs CA_FILE=/path/to/corporate-root.crt" >&2; exit 2; }
	./scripts/install-host-ca.sh "$(CA_FILE)"

clean: reset ## alias for reset
