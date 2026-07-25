"""Tests for multi-agent context propagation (RunContext sharing)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.orchestration.manifest import OrchestrationManifest
from nexus.orchestration.runtime import OrchestrationRuntime
from nexus.runner.result import AgentRunResult
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext
from nexus.utils.jinja import render_system_prompt


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "orchestration"


def _agent(name: str) -> AgentConfig:
    return AgentConfig(
        name=name,
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role=name, goal="work"),
    )


def test_derive_child_copies_identity_and_services():
    db = object()
    parent = RunContext(
        tenant_id="t1",
        company_id="c1",
        user_id="u1",
        user_name="Alice",
        request_id="req-1",
        channel="api",
        branch_id="b1",
        auth={"token": "x"},
        metadata={"plan": "pro"},
        state={"step": 1},
    )
    parent.bind_services(db=db)

    child = parent.derive_child(session_id="child-s", is_subagent=True, include_context=True)
    assert child.company_id == "c1"
    assert child.user_name == "Alice"
    assert child.request_id == "req-1"
    assert child.channel == "api"
    assert child.branch_id == "b1"
    assert child.auth == {"token": "x"}
    assert child.metadata == {"plan": "pro"}
    assert child.state == {"step": 1}
    assert child.service("db") is db


def test_derive_child_isolated_omits_bags():
    parent = RunContext(metadata={"a": 1}, state={"b": 2})
    child = parent.derive_child(session_id="s", include_context=False)
    assert child.metadata == {}
    assert child.state == {}


def test_member_inherits_identity_from_group_at_init():
    group_ctx = RunContext(
        tenant_id="t1",
        company_id="co-9",
        user_id="u1",
        session_id="root",
    )
    group_ctx.bind_services(db=object())
    orch = AgentOrchestrator(
        config=AgentGroupConfig(
            name="g",
            pattern="pipeline",
            members=[_agent("a")],
        ),
        run_context=group_ctx,
    )
    member_ctx = orch._members["a"].run_context
    assert member_ctx.company_id == "co-9"
    assert member_ctx.service("db") is group_ctx.service("db")


def test_context_sharing_isolated_keeps_empty_member_bags():
    orch = AgentOrchestrator(
        config=AgentGroupConfig(
            name="g",
            pattern="pipeline",
            context_sharing="isolated",
            members=[_agent("a")],
        ),
        run_context=RunContext(session_id="s1", metadata={"k": 1}, state={"s": 2}),
    )
    assert orch._members["a"].run_context.metadata == {}
    assert orch._members["a"].run_context.state == {}


def test_sync_down_at_run_time_sees_live_group_state():
    orch = AgentOrchestrator(
        config=AgentGroupConfig(
            name="g",
            pattern="pipeline",
            context_sharing="inherit",
            members=[_agent("a")],
        ),
        run_context=RunContext(session_id="s1"),
    )
    orch.run_context.state["live"] = True
    orch._sync_down(orch._members["a"])
    assert orch._members["a"].run_context.state.get("live") is True
    assert orch._members["a"].run_context.metadata["nexus_delegation"]["group"] == "g"


def test_sync_up_shared_merges_without_delegation_breadcrumb():
    orch = AgentOrchestrator(
        config=AgentGroupConfig(
            name="g",
            pattern="pipeline",
            context_sharing="shared",
            members=[_agent("a")],
        ),
        run_context=RunContext(session_id="s1"),
    )
    member = orch._members["a"]
    member.run_context.state["from_member"] = 42
    member.run_context.metadata["nexus_delegation"] = {"group": "g"}
    member.run_context.metadata["extra"] = "yes"
    orch._sync_up(member)
    assert orch.run_context.state.get("from_member") == 42
    assert orch.run_context.metadata.get("extra") == "yes"
    assert "nexus_delegation" not in orch.run_context.metadata


@pytest.mark.asyncio
async def test_pipeline_shared_propagates_state_to_next_member():
    group = AgentGroupConfig(
        name="pipe",
        pattern="pipeline",
        context_sharing="shared",
        members=[_agent("first"), _agent("second")],
    )
    orch = AgentOrchestrator(
        config=group,
        storage_config=SessionManager(),
        run_context=RunContext(session_id="pipe-1"),
    )

    done = AgentRunResult(
        session_id="s",
        final_response="step1",
        turns_used=1,
        status="completed",
        duration_ms=1,
    )

    async def first_run(_msg, **kwargs):
        orch._members["first"].run_context.set_state("handoff", "data")
        return done

    second_run = AsyncMock(
        return_value=AgentRunResult(
            session_id="s2",
            final_response="step2",
            turns_used=1,
            status="completed",
            duration_ms=1,
        )
    )

    with patch.object(orch._members["first"], "run", side_effect=first_run), patch.object(
        orch._members["second"], "run", second_run
    ):
        await orch.run("go")

    assert orch.run_context.state.get("handoff") == "data"
    assert second_run.await_args is not None


def test_render_system_prompt_shows_delegation_block():
    persona = AgentPersonaConfig(role="Worker", goal="Help").model_dump()
    rendered = render_system_prompt(
        persona,
        run_context=RunContext(
            metadata={
                "nexus_delegation": {
                    "group": "billing_team",
                    "delegated_by": "supervisor",
                }
            }
        ),
    )
    assert "## Delegated task" in rendered
    assert "billing_team" in rendered
    assert "supervisor" in rendered


def test_render_system_prompt_no_delegation_block_without_breadcrumb():
    persona = AgentPersonaConfig(role="Worker", goal="Help").model_dump()
    rendered = render_system_prompt(
        persona,
        run_context=RunContext(),
    )
    assert "## Delegated task" not in rendered


def test_yaml_context_sharing_resolves():
    manifest = OrchestrationManifest.load(FIXTURES / "context_sharing.yaml")
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(session_id="ctx-yaml"),
    )
    assert isinstance(runtime.executor, AgentOrchestrator)
    assert runtime.executor.config.context_sharing == "shared"
