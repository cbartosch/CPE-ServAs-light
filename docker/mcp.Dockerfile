# Base image, parameterised.
#
# The Docker DAEMON fetches this manifest before any build layer exists, so none
# of the in-image CA staging below is reached. A corporate TLS intercept therefore
# fails the build with:
#
#   failed to resolve source metadata for docker.io/library/python:3.12-slim:
#   tls: failed to verify certificate: x509: certificate signed by unknown authority
#
# That is a host and daemon problem, not a pip problem. Point BASE_IMAGE at an
# internal mirror to avoid the public registry entirely:
#
#   BASE_IMAGE=artifactory.example.com/docker-remote/python:3.12-slim
#
# Set it in .env and compose passes it through.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=
ARG PIP_STRICT_TLS=0

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

COPY docker/certs/ /usr/local/share/ca-certificates/lpr-extra/
RUN update-ca-certificates

COPY requirements-mcp.txt ./
COPY vendor/ /wheels/
# Dependency install, in order of preference:
#   1. vendored wheels  -- no network at all (scripts/vendor-wheels.*)
#   2. configured index -- PIP_INDEX_URL, e.g. an internal Artifactory mirror
#   3. verified PyPI    -- normal networks
#   4. trusted-host     -- networks that re-sign HTTPS with a corporate CA
# Tier 4 keeps the proxy's own inspection but stops verifying the chain. Set
# PIP_STRICT_TLS=1 to refuse it and fail loudly instead, or stage the corporate
# CA into docker/certs/ to keep verification with no fallback needed.
RUN set -eu; \
    EXTRA=""; \
    IDX="${PIP_INDEX_URL:-}"; \
    if [ -n "$IDX" ]; then EXTRA="--index-url $IDX"; fi; \
    if ls /wheels/*.whl >/dev/null 2>&1; then \
      echo "pip: installing from vendored wheels, no network required"; \
      python -m pip install --no-index --find-links=/wheels -r requirements-mcp.txt; \
    elif python -m pip install $EXTRA -r requirements-mcp.txt; then \
      echo "pip: certificate verification succeeded"; \
    elif [ "${PIP_STRICT_TLS:-0}" = "1" ]; then \
      echo "pip: verification failed and PIP_STRICT_TLS=1 -- refusing to fall back" >&2; \
      echo "pip: stage a CA (scripts/capture-ca.*) or set PIP_INDEX_URL" >&2; \
      exit 1; \
    else \
      echo "pip: verification failed, retrying with trusted hosts (corporate proxy)" >&2; \
      python -m pip install $EXTRA \
        --trusted-host pypi.org \
        --trusted-host files.pythonhosted.org \
        --trusted-host pypi.python.org \
        -r requirements-mcp.txt; \
    fi

COPY src ./src

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8100
