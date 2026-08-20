"""CLI wiring: nexus run must load a YAML path and pass a RunContext."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.cli.main import _run_manifest
from nexus.orchestration import OrchestrationManifest
from nexus.tools.context import RunContext

FIXTURES = Path(__file__).parent / "fixtures" / "orchestration"


@pytest.mark.asyncio
async def test_run_manifest_loads_yaml_and_passes_run_context():
    captured: dict = {}

    fake_runtime = MagicMock()
    fake_runtime.run = AsyncMock(return_value="ok")

    def fake_from_manifest(manifest, *, run_context, **_kwargs):
        captured["manifest"] = manifest
        captured["run_context"] = run_context
        return fake_runtime

    with patch(
        "nexus.orchestration.OrchestrationRuntime.from_manifest",
        side_effect=fake_from_manifest,
    ):
        await _run_manifest(FIXTURES / "basic.yaml", "hello")

    assert isinstance(captured["manifest"], OrchestrationManifest)
    assert captured["manifest"].schema.root == "research_pipeline"
    assert isinstance(captured["run_context"], RunContext)
    fake_runtime.run.assert_awaited_once_with("hello")

    captured: dict = {}

    fake_runtime = MagicMock()
    fake_runtime.run = AsyncMock(return_value="ok")

    def fake_from_manifest(manifest, *, run_context, **_kwargs):
        captured["manifest"] = manifest
        captured["run_context"] = run_context
        return fake_runtime

    with patch(
        "nexus.orchestration.OrchestrationRuntime.from_manifest",
        side_effect=fake_from_manifest,
    ):
        await _run_manifest(FIXTURES / "basic.yaml", "hello")

    assert isinstance(captured["manifest"], OrchestrationManifest)
    assert captured["manifest"].schema.root == "research_pipeline"
    assert isinstance(captured["run_context"], RunContext)
    fake_runtime.run.assert_awaited_once_with("hello")
