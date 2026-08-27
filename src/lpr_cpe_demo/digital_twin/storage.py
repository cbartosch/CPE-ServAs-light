from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import time
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path

from .models import GenerationConfig

_RUN_RE = re.compile(r"^RUN-[0-9]{8}-[A-F0-9]{20}$")
_ACTIVE_RUN_FILE = "active_run.json"

# Run identifiers include the immutable generation schema as well as the user
# configuration.  This prevents an older run generated with a superseded
# topology algorithm from being silently reused after the code is upgraded.
RUN_SCHEMA_VERSION = "lpr-digital-twin-run-v2-delimiter-region"


def canonical_config(config: GenerationConfig) -> bytes:
    data = config.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def derive_run_id(config: GenerationConfig) -> str:
    material = RUN_SCHEMA_VERSION.encode("utf-8") + b"\0" + canonical_config(config)
    digest = hashlib.sha256(material).hexdigest().upper()[:20]
    return f"RUN-{config.run_date:%Y%m%d}-{digest}"


def safe_run_path(data_root: Path, run_id: str) -> Path:
    if not _RUN_RE.fullmatch(run_id):
        raise ValueError("invalid run_id")
    root = data_root.resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("run path escapes data root")
    return path


def _read_catalog_run_id(path: Path) -> str | None:
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    run_id = catalog.get("run_id")
    if not isinstance(run_id, str) or run_id != path.parent.name:
        return None
    try:
        if safe_run_path(path.parents[1], run_id) != path.parent.resolve():
            return None
    except ValueError:
        return None
    return run_id


def _latest_catalog_run_id(data_root: Path) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    for catalog_path in data_root.glob("RUN-*/catalog.json"):
        run_id = _read_catalog_run_id(catalog_path)
        if run_id is None:
            continue
        try:
            stat = catalog_path.stat()
        except OSError:
            continue
        candidates.append((stat.st_mtime_ns, stat.st_ctime_ns, run_id))
    return max(candidates)[2] if candidates else None


def _active_pointer_run_id(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("run_id"), str):
        return value["run_id"]
    return None


def set_active_run(data_root: Path, run_id: str) -> str:
    """Persist a validated active run pointer atomically."""
    root = Path(data_root).resolve()
    run_path = safe_run_path(root, run_id)
    catalog_path = run_path / "catalog.json"
    if _read_catalog_run_id(catalog_path) != run_id:
        raise FileNotFoundError(f"run not found: {run_id}")

    root.mkdir(parents=True, exist_ok=True)
    pointer = root / _ACTIVE_RUN_FILE
    temporary = root / f".{_ACTIVE_RUN_FILE}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps({"run_id": run_id}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        replace_with_retry(temporary, pointer)
    finally:
        temporary.unlink(missing_ok=True)
    return run_id


def get_active_run(data_root: Path) -> str | None:
    """Return the active run, repairing a missing or stale pointer from catalogs."""
    root = Path(data_root).resolve()
    pointer = root / _ACTIVE_RUN_FILE
    run_id = _active_pointer_run_id(pointer)
    if run_id is not None:
        try:
            catalog_path = safe_run_path(root, run_id) / "catalog.json"
        except ValueError:
            catalog_path = None
        if catalog_path is not None and _read_catalog_run_id(catalog_path) == run_id:
            return run_id

    recovered = _latest_catalog_run_id(root) if root.exists() else None
    if recovered is None:
        return None
    try:
        set_active_run(root, recovered)
    except OSError:
        # Recovery remains useful on a read-only replica even when the pointer
        # cannot be repaired there.
        pass
    return recovered


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_with_retry(
    source: Path,
    destination: Path,
    *,
    attempts: int = 20,
    initial_delay: float = 0.025,
    max_delay: float = 0.25,
) -> None:
    """Atomically replace a file or directory, tolerating transient Windows locks.

    Virus scanners, indexers and other Windows filter drivers can briefly hold a
    just-closed file inside a directory. The source remains intact when
    ``os.replace`` raises ``PermissionError``, so a short bounded retry preserves
    the same atomic publication semantics without masking persistent failures.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    delay = initial_delay
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(delay)
            delay = min(max_delay, max(initial_delay, delay * 1.5))


def write_jsonl_gz(path: Path, rows: Iterable[dict]) -> int:
    """Write deterministic gzip JSONL (mtime=0, no embedded filename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as f:
                for row in rows:
                    f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                    count += 1
    return count


def atomic_write_jsonl_gz(path: Path, rows: Iterable[dict]) -> int:
    """Replace a dataset atomically after a complete deterministic write."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        count = write_jsonl_gz(tmp, rows)
        replace_with_retry(tmp, path)
        return count
    finally:
        if tmp.exists():
            tmp.unlink()


def iter_jsonl_gz(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def load_jsonl_gz(path: Path, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    for row in iter_jsonl_gz(path):
        rows.append(row)
        if limit is not None and len(rows) >= limit:
            break
    return rows
