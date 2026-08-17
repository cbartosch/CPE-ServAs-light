# Offline and Low-Resource Operation

## First build

The source bundle is complete, but the first Docker build requires access to the Python and PostgreSQL base images and the pinned packages. After the images are built, all fake-model scenarios run without an external LLM API.

On a controlled corporate network, use the TLS and mirror guidance in `ENVIRONMENT_COMPATIBILITY.md` instead of disabling certificate verification.

## Low-resource overlay

```bash
docker compose -f docker-compose.yml -f docker-compose.low-resource.yml up --build -d --wait
```

The overlay caps the four runtime containers at approximately 2.7 GB combined:

| Service | Memory limit |
|---|---:|
| PostgreSQL | 512 MB |
| MCP simulator | 384 MB |
| FastAPI/LangGraph | 1,024 MB |
| Streamlit | 768 MB |

Startup and scenario execution can be slower under these limits. The full verification test container requires additional temporary headroom.

## Reuse after the first connected build

List the exact Compose image names first:

```bash
docker compose images
```

Then export the application, UI, MCP and PostgreSQL images shown by that command. A typical Compose project named `lpr-cpe-demo` uses names similar to:

```bash
docker save \
  lpr-cpe-demo-api \
  lpr-cpe-demo-ui \
  lpr-cpe-demo-mcp-sim \
  postgres:17-alpine \
  -o lpr-cpe-demo-images.tar
```

Docker Compose image names vary by Compose version and project settings, so use the names displayed by `docker compose images` rather than assuming them.

On the offline laptop:

```bash
docker load -i lpr-cpe-demo-images.tar
docker compose up -d --no-build --wait
```

The external OpenAI and Anthropic modes still require network access. Keep `MODEL_PROVIDER=fake` for a fully local demonstration.
