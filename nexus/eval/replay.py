"""Session record/replay for regression testing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SessionReplayer:
    """Load recorded session JSON for replay assertions."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text())

    @property
    def turns(self) -> list[dict[str, Any]]:
        return self.data.get("turns", [])

    def tool_names(self) -> list[str]:
        names: list[str] = []
        for turn in self.turns:
            for tc in turn.get("tool_calls", []):
                names.append(tc.get("tool_name", ""))
        return names
