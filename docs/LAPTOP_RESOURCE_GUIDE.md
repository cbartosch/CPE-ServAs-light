# Laptop Resource Guide

## Recommended Docker Desktop allocation

| Resource | Minimum | Preferred |
|---|---:|---:|
| CPU | 2 cores | 4 cores |
| Docker memory | 4 GB | 6–8 GB |
| Free disk | 5 GB | 8–10 GB |

The default fake model keeps CPU and memory use modest. An external LLM call runs outside the laptop but requires network access.

## Windows

Use Docker Desktop with the WSL 2 backend. Run scripts from PowerShell or a WSL shell. Ensure the project is stored in a filesystem path Docker Desktop can mount efficiently.

## macOS

Use Docker Desktop and allocate at least 4 GB to Docker, preferably 6–8 GB. Apple Silicon is supported because the selected container images are multi-architecture.

## Corporate laptop considerations

Proxy, VPN and endpoint-security controls can block image pulls or external model APIs. The default fake model and simulated MCP tools do not require an external LLM account after images have been downloaded.
