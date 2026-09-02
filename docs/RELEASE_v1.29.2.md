# Release v1.29.2 — target Ruff import-block closure

This release is the complete P1/P2 application release with the final target
Ruff 0.13.3 import-order finding corrected.

## Correction

`src/lpr_cpe_demo/ui/client.py` now uses the canonical import trailer expected
by Ruff/isort when a module-level constant follows the import block:

```python
from __future__ import annotations

from typing import Any

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
```

The previous file contained an additional blank line between the import block
and the first constant. The target Windows gate reported this as `I001`.

## Retained P1/P2 capabilities

- Shared repair/install assurance episode and durable handoff linkage.
- PostgreSQL-backed episode and append-only event persistence.
- Mandatory pre-action and immediate post-action health evidence.
- Durable post-action quarantine with repeated observations.
- Release, reopen, extend and escalate transitions.
- Lease-based retry-safe quarantine scheduling.
- Simulation-only action execution and production writes disabled.
- Canonical DvSum CADDI terminology.

## Mandatory target gates

The delivery verifier requires Python 3.14.7, pytest 9.0.2 and Ruff 0.13.3,
then runs compilation, Ruff, focused P1/P2 tests, the complete pytest suite,
the scenario matrix, manifest verification and Docker validation.
