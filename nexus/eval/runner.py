"""Dataset-driven eval runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class EvalCase:
    id: str
    input: str
    expect_contains: Optional[str] = None
    expect_tools: list[str] = field(default_factory=list)


class EvalRunner:
    """Run eval cases against an async runner callable."""

    def __init__(self, cases: list[EvalCase]):
        self.cases = cases

    async def run_all(self, runner_fn) -> dict[str, Any]:
        passed = 0
        results = []
        for case in self.cases:
            out = await runner_fn(case.input)
            text = getattr(out, "final_response", None) or str(out)
            ok = True
            if case.expect_contains and case.expect_contains not in (text or ""):
                ok = False
            if ok:
                passed += 1
            results.append({"id": case.id, "ok": ok, "output": text})
        return {"passed": passed, "total": len(self.cases), "results": results}


def run_eval_cli(dataset: Path | None) -> None:
    cases = [
        EvalCase(id="smoke", input="Hello", expect_contains=None),
    ]
    if dataset and dataset.exists():
        raw = json.loads(dataset.read_text())
        cases = [EvalCase(**item) for item in raw.get("cases", [])]

    async def _noop(_msg: str):
        return type("R", (), {"final_response": "ok"})()

    import asyncio

    report = asyncio.run(EvalRunner(cases).run_all(_noop))
    print(json.dumps(report, indent=2))
