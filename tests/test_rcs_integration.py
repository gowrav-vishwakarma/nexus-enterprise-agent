"""RCS end-to-end integration tests (mocked + opt-in live LLM)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.agent import AgentPersonaConfig, TurnConfig
from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

NOISE_BLOB = (
    "PANDAS COOKBOOK: How to make chocolate chip cookies with butter, flour, and sugar. "
    "Season the dough with vanilla extract. Bake at 350F for 12 minutes. "
    "This recipe has nothing to do with physics, quantum mechanics, or documentation. "
) * 8

RCS_SUMMARY = "I checked noise_lookup but it does not contain what I want."

USER_PROMPT = (
    "Find quantum entanglement info in our docs. "
    "First call global.noise_lookup with query 'quantum entanglement'. "
    "If that result is not about quantum physics, call global.doc_search next and include "
    f"_context_updates summarizing the noise_lookup result as: '{RCS_SUMMARY}'"
)


@tool(name="noise_lookup", description="General lookup that may return unrelated content.")
def noise_lookup(query: str) -> str:
    return f"[noise_lookup for '{query}'] {NOISE_BLOB}"


@tool(name="doc_search", description="Search internal documentation.")
def doc_search(query: str) -> str:
    return f"Doc hit for '{query}': quantum entanglement is covered in section 4.2."


def _register_rcs_tools(registry: ToolRegistry) -> None:
    registry.register_tool(noise_lookup)
    registry.register_tool(doc_search)


def _rcs_agent_config(llm_config: LLMProviderConfig) -> AgentConfig:
    return AgentConfig(
        name="rcs-test-agent",
        llm=llm_config,
        rcs=RuntimeContextSummarizerConfig(enabled=True),
        tool_plugins=["global"],
        turns=TurnConfig(max_turns=5, turn_timeout_seconds=120),
        persona=AgentPersonaConfig(
            role="Research assistant",
            goal="Find correct documentation and manage context efficiently",
        ),
    )


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


def llm_config_from_env() -> LLMProviderConfig:
    """Build LLM config from NEXUS_LLM_* or PLATFORM_OPENAI_KEY env vars."""
    _load_env()
    provider = os.getenv("NEXUS_LLM_PROVIDER", "openai")
    base_url = os.getenv("NEXUS_LLM_BASE_URL", "") or None
    model = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")
    api_key = os.getenv("NEXUS_LLM_API_KEY") or os.getenv("PLATFORM_OPENAI_KEY", "")
    if not api_key or api_key.startswith("sk-your-"):
        pytest.skip("No LLM API key configured (set NEXUS_LLM_API_KEY or PLATFORM_OPENAI_KEY)")
    return LLMProviderConfig(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
    )


def _summary_matches_intent(summary: str) -> bool:
    lower = summary.lower()
    return any(
        phrase in lower
        for phrase in ("checked", "not contain", "does not", "not relevant", "unrelated")
    )


def _assert_rcs_applied(session, agent_config: AgentConfig) -> None:
    """Shared assertions for mocked and live RCS e2e runs."""
    assert len(session.turns) >= 2

    noise_tc = session.turns[0].tool_calls[0]
    assert noise_tc.tool_name == "global.noise_lookup"
    assert noise_tc.tc_id == "TC1"
    assert noise_tc.tc_index == 1
    assert "PANDAS COOKBOOK" in noise_tc.raw_response
    assert noise_tc.summarized_response is not None

    has_updates = any(turn.context_updates_received for turn in session.turns)
    assert has_updates or noise_tc.summarized_response is not None

    summary = noise_tc.summarized_response or ""
    assert _summary_matches_intent(summary), f"Unexpected summary: {summary!r}"

    for turn in session.turns[1:]:
        for tc in turn.tool_calls:
            assert "_context_updates" not in tc.tool_input

    messages = ContextWindowBuilder().build(session, agent_config)
    tool_contents = [m["content"] for m in messages if m.get("role") == "tool"]
    assert any(RCS_SUMMARY.lower() in c.lower() or _summary_matches_intent(c) for c in tool_contents)
    assert not any("PANDAS COOKBOOK" in c for c in tool_contents)

    assert session.total_tokens_saved_by_rcs > 0


@pytest.mark.asyncio
async def test_rcs_e2e_mocked_llm():
    """Deterministic RCS pipeline: irrelevant tool result compressed on next tool call."""
    from nexus.llm.response import LLMResponse, ToolCallRequest, TokenUsage

    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    agent_config = _rcs_agent_config(llm_config)

    registry = ToolRegistry()
    _register_rcs_tools(registry)

    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    response_turn_0 = LLMResponse(
        content="Let me try the general lookup first.",
        tool_calls=[
            ToolCallRequest(
                id="call-1",
                tool_name="global.noise_lookup",
                tool_input={"query": "quantum entanglement"},
            )
        ],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        finish_reason="tool_calls",
        raw_response={},
    )

    response_turn_2 = LLMResponse(
        content="Found quantum entanglement in section 4.2.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40),
        finish_reason="stop",
        raw_response={},
    )

    call_count = 0

    async def dynamic_mock_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return response_turn_0
        if call_count == 2:
            sess = await manager.load_session("rcs-mock-sess")
            tc_id = sess.turns[0].tool_calls[0].tc_id
            return LLMResponse(
                content="The noise result was useless; searching docs instead.",
                tool_calls=[
                    ToolCallRequest(
                        id="call-2",
                        tool_name="global.doc_search",
                        tool_input={
                            "query": "quantum entanglement",
                            "_context_updates": [
                                {"tc_id": tc_id, "summary": RCS_SUMMARY},
                            ],
                        },
                    )
                ],
                usage=TokenUsage(prompt_tokens=20, completion_tokens=12, total_tokens=32),
                finish_reason="tool_calls",
                raw_response={},
            )
        return response_turn_2

    mock_chat = AsyncMock(side_effect=dynamic_mock_chat)

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run(
            user_message=USER_PROMPT,
            session_id="rcs-mock-sess",
        )

    assert result.status == "completed"
    assert result.total_tokens_saved_by_rcs > 0

    sess = await manager.load_session("rcs-mock-sess")
    assert sess is not None
    _assert_rcs_applied(sess, agent_config)

    assert sess.turns[1].context_updates_received
    assert sess.turns[1].context_updates_received[0]["summary"] == RCS_SUMMARY


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_rcs_e2e_live_llm():
    """Live LLM RCS test: model compresses irrelevant noise_lookup via _context_updates."""
    llm_config = llm_config_from_env()
    agent_config = _rcs_agent_config(llm_config)

    registry = ToolRegistry()
    _register_rcs_tools(registry)

    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    try:
        result = await runner.run(
            user_message=USER_PROMPT,
            session_id="rcs-live-sess",
        )
    except Exception as exc:
        pytest.fail(f"Live RCS run failed: {exc}")

    sess = await manager.load_session("rcs-live-sess")
    assert sess is not None

    try:
        _assert_rcs_applied(sess, agent_config)
    except AssertionError as exc:
        debug = {
            "turns": len(sess.turns),
            "total_tokens_saved_by_rcs": sess.total_tokens_saved_by_rcs,
            "result_tokens_saved": result.total_tokens_saved_by_rcs,
            "tool_calls": [
                {
                    "turn": i,
                    "tc_id": tc.tc_id,
                    "tool_name": tc.tool_name,
                    "summarized_response": tc.summarized_response,
                }
                for i, turn in enumerate(sess.turns)
                for tc in turn.tool_calls
            ],
            "context_updates": [
                {"turn": i, "updates": turn.context_updates_received}
                for i, turn in enumerate(sess.turns)
            ],
        }
        pytest.fail(f"{exc}\nSession debug: {debug}")
