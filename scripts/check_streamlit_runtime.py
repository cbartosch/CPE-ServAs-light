from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("STREAMLIT_SMOKE_PORT", "8511"))
URL = f"http://127.0.0.1:{PORT}/_stcore/health"


def main() -> int:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    # The default Cockpit page handles an unavailable API cleanly. Point it at a closed local port so
    # this test verifies Streamlit startup and page construction without requiring the full stack.
    env["API_URL"] = "http://127.0.0.1:9"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "src/lpr_cpe_demo/ui/app.py"),
        "--server.address=127.0.0.1",
        f"--server.port={PORT}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    process = subprocess.Popen(  # noqa: S603 - fixed executable and local source path
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output: list[str] = []
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                if process.stdout is not None:
                    output.extend(process.stdout.readlines())
                raise RuntimeError(
                    "Streamlit exited before becoming healthy:\n" + "".join(output[-80:])
                )
            try:
                with urllib.request.urlopen(URL, timeout=2) as response:  # noqa: S310 - local health URL
                    body = response.read().decode("utf-8", errors="replace")
                    if response.status == 200 and "ok" in body.lower():
                        print("Streamlit runtime health check: PASS")
                        return 0
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(0.5)
        if process.stdout is not None:
            output.extend(process.stdout.readlines())
        raise RuntimeError("Streamlit did not become healthy:\n" + "".join(output[-80:]))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
