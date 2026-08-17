#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PORTS = [5432, 8000, 8100, 8501]


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    print("LPR CPE demo preflight")
    if not (ROOT / ".env").exists():
        print("ERROR: .env is missing")
        return 1
    docker = shutil.which("docker")
    if not docker:
        print("ERROR: Docker CLI was not found. Install/start Docker Desktop and reopen the terminal.")
        return 1
    try:
        subprocess.run([docker, "compose", "version"], check=True, timeout=15)
        subprocess.run([docker, "info"], check=True, timeout=30, stdout=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: Docker Desktop is not ready: {exc}")
        return 1
    busy = [port for port in PORTS if not port_available(port)]
    if busy:
        print(f"WARNING: ports already in use: {busy}. Change them in .env before starting.")
    print(f"Project directory: {ROOT}")
    print(f"Platform: {sys.platform}; CPU count: {os.cpu_count() or 'unknown'}")
    print("Preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
