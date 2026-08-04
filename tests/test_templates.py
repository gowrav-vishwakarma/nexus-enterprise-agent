"""Starter templates must keep importing and building as the framework moves.

A template that no longer runs is worse than no template, so these load each one
the way a user would and build the objects it advertises. No LLM calls are made.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_DATA_ROOT", str(tmp_path / "agent-data"))
    monkeypatch.setenv("NEXUS_DATA_ROOT", str(tmp_path / "tenants"))


def test_personal_agent_template_builds_a_runner():
    module = _load("tpl_personal", TEMPLATES / "personal-agent" / "main.py")

    runner = module.build_agent()

    assert runner.config.memory.enabled
    assert runner.run_context.should_persist
    assert {"save_note", "read_notes"} <= set(runner.tool_registry.tool_names())


def test_personal_agent_notes_tools_round_trip(tmp_path, monkeypatch):
    module = _load("tpl_personal", TEMPLATES / "personal-agent" / "main.py")
    monkeypatch.setattr(module, "NOTES_FILE", tmp_path / "notes.md")

    module.save_note("buy milk")

    assert "buy milk" in module.read_notes()


def test_background_worker_builds_scheduler_context():
    module = _load("tpl_worker", TEMPLATES / "background-worker" / "main.py")

    job = module.ScheduledJob(id="j1", cron="0 9 * * *", prompt="summarise")
    ctx = module.build_cron_run_context(module.BASE_CONTEXT, job)

    assert ctx.is_cron
    assert ctx.session_id == "cron_j1"
    assert ctx.tenant_id == module.BASE_CONTEXT.tenant_id
    assert module.build_runner().config.name == "background-worker"


@pytest.mark.asyncio
async def test_background_worker_runs_due_jobs_once(monkeypatch):
    module = _load("tpl_worker", TEMPLATES / "background-worker" / "main.py")
    ran: list[str] = []

    async def fake_run_job(job):
        ran.append(job.prompt)

    monkeypatch.setattr(module, "run_job", fake_run_job)
    await module.main(once=True)

    assert len(ran) == 2


def test_saas_chat_template_exposes_its_routes():
    pytest.importorskip("fastapi")
    module = _load("tpl_saas", TEMPLATES / "saas-chat" / "main.py")

    paths = {route.path for route in module.app.routes}

    assert {"/health", "/v1/chat", "/v1/chat/stream", "/v1/sessions/{session_id}/stream"} <= paths


def test_saas_chat_requires_a_tenant():
    """A missing tenant must fail closed, not silently share one boundary."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    module = _load("tpl_saas", TEMPLATES / "saas-chat" / "main.py")
    client = TestClient(module.app)

    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 401
