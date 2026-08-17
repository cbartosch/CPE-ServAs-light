from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def command_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "not available"
    return (result.stdout or result.stderr).strip().splitlines()[0]


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def memory_gb() -> float | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return None
    return pages * page_size / (1024**3)


root = Path(__file__).resolve().parents[1]
free = shutil.disk_usage(root).free / (1024**3)
print("LPR CPE demo environment check")
print(f"OS: {platform.platform()}")
print(f"Architecture: {platform.machine()}")
print(f"Python: {sys.version.split()[0]}")
print(f"Logical CPUs: {os.cpu_count()}")
ram = memory_gb()
print(f"Host RAM: {ram:.1f} GB" if ram is not None else "Host RAM: unavailable")
print(f"Free disk at bundle path: {free:.1f} GB")
print(f"Docker: {command_version(['docker', '--version'])}")
print(f"Docker Compose: {command_version(['docker', 'compose', 'version'])}")
for port in (5432, 8000, 8100, 8501):
    print(f"Port {port}: {'available' if port_available(port) else 'in use'}")
proxy_names = [
    name
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")
    if os.getenv(name)
]
print(f"Proxy environment: {', '.join(proxy_names) if proxy_names else 'not set'}")
cert_dir = root / "docker" / "certs"
staged_certs = sorted(cert_dir.glob("*.crt"))
print(f"Staged corporate CA certificates: {len(staged_certs)}")
if os.getenv("PIP_INDEX_URL"):
    print("PIP_INDEX_URL: configured (value redacted)")

warnings: list[str] = []
if ram is not None and ram < 4:
    warnings.append("Less than 4 GB host RAM detected; reduce other Docker workloads.")
if free < 5:
    warnings.append("Less than 5 GB free disk detected.")
if shutil.which("docker") is None:
    warnings.append("Docker CLI not found. Install/start Docker Desktop before launching the demo.")
if proxy_names and not staged_certs:
    warnings.append(
        "A proxy is configured but no corporate CA is staged. If the proxy re-signs HTTPS, "
        "run scripts/stage-ca.sh or scripts/stage-ca.ps1 before building."
    )
if warnings:
    print("\nWarnings:")
    for warning in warnings:
        print(f"- {warning}")
else:
    print("\nEnvironment check: compatible with the recommended demo footprint.")
