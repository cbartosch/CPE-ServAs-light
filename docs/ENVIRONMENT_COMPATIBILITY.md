# Docker Desktop Environment Compatibility

The bundle targets Windows, macOS and Linux laptops running Docker Desktop or Docker Engine with Compose v2. Both x86_64 and arm64 are expected to work because the selected Python and PostgreSQL images are multi-architecture.

## Recommended resources

| Resource | Minimum | Recommended |
|---|---:|---:|
| Docker memory | 4 GB | 6–8 GB |
| Free disk | 5 GB | 8–10 GB |
| CPU | 2 logical cores | 4 or more |
| Architecture | x86_64 or arm64 | x86_64 or arm64 |

The application and MCP images use `python:3.12-slim`; PostgreSQL uses `postgres:17-alpine`.

Run:

```bash
python scripts/check_environment.py
```

The checker reports the operating system, architecture, Python version, CPU count, available RAM and disk, Docker/Compose availability, default-port availability, proxy presence and staged corporate CA count.

## First-build network and TLS requirements

The first build needs access to the selected base images and exact Python package pins. The default fake-model scenarios are local after the images are built.

Run the connectivity doctor before diagnosing a failed build:

```bash
./scripts/tls-doctor.sh
```

```powershell
.\scripts\tls-doctor.ps1
```

The doctor distinguishes:

- DNS failure;
- proxy or CONNECT failure;
- TLS certificate-chain failure;
- malformed or non-CA certificates staged in `docker/certs/`.

### Corporate HTTPS inspection

When a corporate proxy re-signs HTTPS, obtain the corporate root or issuing CA from IT/security. Stage it into both images:

```bash
./scripts/stage-ca.sh /path/to/corporate-root.crt
```

```powershell
.\scripts\stage-ca.ps1 -CaFile C:\path\corporate-root.cer
```

The staging tools accept PEM or DER, require `CA:TRUE`, refuse website leaf certificates and place one PEM certificate in each `.crt` file. Both Dockerfiles run Debian `update-ca-certificates` and point Python HTTP clients at the same system bundle.

Do not use `--trusted-host`, `verify=false`, an insecure HTTP package index or a website leaf certificate as a trust anchor.

### Proxy and package mirror

The Compose build forwards host `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` values as build arguments. An internal Python package mirror can be configured through `PIP_INDEX_URL` in `.env` or the launching shell. Avoid embedding long-lived credentials in that URL because build arguments may be visible in build metadata.

## Runtime ports

| Service | Default host port |
|---|---:|
| PostgreSQL | 5432 |
| FastAPI | 8000 |
| MCP simulator | 8100 |
| Streamlit | 8501 |

Change the corresponding variables in `.env` when a port is already occupied.

No GPU is required. External LLM calls are optional and use the provider API configured on the backend only.
