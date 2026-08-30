# Base image, parameterised.
#
# The Docker DAEMON fetches this manifest before any build layer exists, so none
# of the in-image CA staging below is reached. A corporate TLS intercept therefore
# fails the build with:
#
#   failed to resolve source metadata for docker.io/library/python:3.14.7-slim-bookworm:
#   tls: failed to verify certificate: x509: certificate signed by unknown authority
#
# That is a host and daemon problem, not a pip problem. Point BASE_IMAGE at an
# internal mirror to avoid the public registry entirely:
#
#   BASE_IMAGE=artifactory.example.com/docker-remote/python:3.14.7-slim-bookworm
#
# Set it in .env and compose passes it through.
ARG BASE_IMAGE=python:3.14.7-slim-bookworm
FROM ${BASE_IMAGE} AS base

ARG PIP_INDEX_URL=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Optional corporate root/issuing CA certificates. Keep one CA per .crt file.
COPY docker/certs/ /usr/local/share/ca-certificates/lpr-extra/
RUN update-ca-certificates

COPY requirements-app.txt pyproject.toml README.md ./
COPY vendor/ /wheels/
# Dependency install, in order of preference:
#   1. vendored wheels  -- no network required
#   2. configured index -- PIP_INDEX_URL, such as an approved mirror
#   3. the default package index with normal certificate verification
# Certificate verification is mandatory; there is no host-trust bypass.
RUN set -eu; \
    EXTRA=""; \
    IDX="${PIP_INDEX_URL:-}"; \
    if [ -n "$IDX" ]; then EXTRA="--index-url $IDX"; fi; \
    if ls /wheels/*.whl >/dev/null 2>&1; then \
      echo "pip: installing from vendored wheels, no network required"; \
      python -m pip install --no-index --find-links=/wheels -r requirements-app.txt; \
    else \
      echo "pip: installing from a TLS-verified package index"; \
      python -m pip install $EXTRA -r requirements-app.txt; \
    fi
COPY src ./src
COPY scripts ./scripts
COPY docs ./docs
COPY tests ./tests
COPY requirements-dev.txt requirements-mcp.txt ./

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

FROM base AS runtime

FROM base AS test
USER root
COPY vendor/ /wheels/
# Dependency install, in order of preference:
#   1. vendored wheels  -- no network required
#   2. configured index -- PIP_INDEX_URL, such as an approved mirror
#   3. the default package index with normal certificate verification
# Certificate verification is mandatory; there is no host-trust bypass.
RUN set -eu; \
    EXTRA=""; \
    IDX="${PIP_INDEX_URL:-}"; \
    if [ -n "$IDX" ]; then EXTRA="--index-url $IDX"; fi; \
    if ls /wheels/*.whl >/dev/null 2>&1; then \
      echo "pip: installing from vendored wheels, no network required"; \
      python -m pip install --no-index --find-links=/wheels -r requirements-dev.txt; \
    else \
      echo "pip: installing from a TLS-verified package index"; \
      python -m pip install $EXTRA -r requirements-dev.txt; \
    fi
USER appuser
CMD ["python", "-m", "pytest", "-q"]
