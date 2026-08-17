from __future__ import annotations

import os
import time

import httpx

checks = {
    "API": os.getenv("API_HEALTH_URL", "http://localhost:8000/health"),
    "MCP": os.getenv("MCP_HEALTH_URL", "http://localhost:8100/health"),
    "Streamlit": os.getenv("UI_HEALTH_URL", "http://localhost:8501/_stcore/health"),
}

for label, url in checks.items():
    last_error = ""
    for _ in range(45):
        try:
            response = httpx.get(url, timeout=3)
            response.raise_for_status()
            print(f"{label}: PASS ({url})")
            break
        except Exception as exc:  # command-line diagnostic
            last_error = str(exc)
            time.sleep(2)
    else:
        raise SystemExit(f"{label}: FAIL ({url}) - {last_error}")
