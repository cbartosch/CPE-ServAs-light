FROM python:3.12-slim

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

COPY docker/certs/ /usr/local/share/ca-certificates/lpr-extra/
RUN update-ca-certificates

COPY requirements-mcp.txt ./
RUN set -eu; \
    if [ -n "${PIP_INDEX_URL:-}" ]; then \
      python -m pip install --upgrade pip --index-url "$PIP_INDEX_URL"; \
      python -m pip install --index-url "$PIP_INDEX_URL" -r requirements-mcp.txt; \
    else \
      python -m pip install --upgrade pip; \
      python -m pip install -r requirements-mcp.txt; \
    fi

COPY src ./src

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8100
