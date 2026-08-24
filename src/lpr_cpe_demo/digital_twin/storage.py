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


def canonical_config(config: GenerationConfig) -> bytes:
    data = config.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def derive_run_id(config: GenerationConfig) -> str:
    digest = hashlib.sha256(canonical_config(config)).hexdigest().upper()[:20]
    return f"RUN-{config.run_date:%Y%m%d}-{digest}"


def safe_run_path(data_root: Path, run_id: str) -> Path:
    if not _RUN_RE.fullmatch(run_id):
        raise ValueError("invalid run_id")
    root = data_root.resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("run path escapes data root")
    return path


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
