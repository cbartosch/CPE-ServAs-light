from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lpr_cpe_demo.config import Settings, get_settings
from lpr_cpe_demo.domain import ScenarioSummary, Technology


class ScenarioCatalog:
    def __init__(self, fixture_dir: Path | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.fixture_dir = fixture_dir or self.settings.fixture_dir

    def _paths(self) -> list[Path]:
        return sorted(self.fixture_dir.glob("*.json"))

    def list(self) -> list[ScenarioSummary]:
        result: list[ScenarioSummary] = []
        for path in self._paths():
            payload = json.loads(path.read_text(encoding="utf-8"))
            result.append(
                ScenarioSummary(
                    name=payload["name"],
                    label=str(payload.get("label") or payload.get("title") or payload["name"]),
                    description=payload["description"],
                    technology=Technology(payload["technology"]),
                    expected_path=list(payload.get("action_sequence", [])),
                )
            )
        return result

    def get(self, name: str) -> dict[str, Any]:
        path = self.fixture_dir / f"{name}.json"
        if not path.exists():
            raise KeyError(f"Unknown scenario: {name}")
        return json.loads(path.read_text(encoding="utf-8"))
