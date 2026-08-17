# Start Here

This bundle is a simulation-only Docker Desktop demonstration. It does not connect to production NXT, CPE, WFM, inventory, TM Forum or jTrack systems.

## 1. Prerequisites

- Docker Desktop with Docker Compose v2
- 4 GB Docker memory minimum; 6–8 GB recommended
- 5 GB free disk minimum
- Host ports 5432, 8000, 8100 and 8501 available, or changed in `.env`

Run the environment and connectivity checks when local Python and Bash/PowerShell are available:

```bash
python scripts/check_environment.py
./scripts/tls-doctor.sh
```

```powershell
python scripts/check_environment.py
.\scripts\tls-doctor.ps1
```

On an HTTPS-inspecting corporate network, obtain the corporate root or issuing CA from IT/security and stage it before the first Docker build:

```bash
./scripts/stage-ca.sh /path/to/corporate-root.crt
```

```powershell
.\scripts\stage-ca.ps1 -CaFile C:\path\corporate-root.cer
```

Do not disable TLS verification or use `--trusted-host`. See `docker/certs/README.md`.

## 2. Start the demo

**Windows PowerShell**

```powershell
.\scripts\start_demo.ps1
```

**macOS, Linux or WSL**

```bash
./scripts/start_demo.sh
```

Open:

- Streamlit operations console: `http://localhost:8501`
- FastAPI documentation: `http://localhost:8000/docs`
- MCP simulator health: `http://localhost:8100/health`

Start a scenario, inspect it in **Incident Workbench**, approve the pending item in **Human Decision Center**, and use **Decision and Model Monitor** to compare deterministic RCA, assisted RCA, gate reason, best action, next-best action and human disposition.

## 3. Run the complete target-laptop verification

```bash
./scripts/verify_docker.sh
```

```powershell
.\scripts\verify_docker.ps1
```

The verification builds the pinned images, checks all health endpoints, exercises a live FastAPI-to-MCP workflow, validates exact installed dependency versions, tests LangGraph interrupt/resume, tests PostgreSQL checkpoint recovery after recreating the workflow service, starts Streamlit, runs all nine scenarios and runs the automated suite with coverage.

The assembly environment did not provide Docker Engine, so this target-laptop verification remains mandatory before presenting the containerized demo. See `BUILD_TEST_REPORT.txt`.

## 4. Stop or reset

```bash
docker compose down
```

To erase PostgreSQL and MCP effect data:

```bash
docker compose down -v
```

The included `.env` is safe for demonstration: fake model, simulated tools and production writes disabled.
