"""Tests for context summarization (summary_text + summarize_on)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.config.context_summary import ContextSummaryConfig
from nexus.config.memory import MemoryConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.context.memory_injector import MemoryPromptInjector
from nexus.context.summarizer import ContextSummarizer
from nexus.context.summary_injector import SummaryPromptInjector
from nexus.llm.response import LLMResponse, TokenUsage
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, TurnRecord


def test_memory_injector_appends_when_template_lacks_block():
    cfg = MemoryConfig(enabled=True, inject_into_prompt=True)
    out = MemoryPromptInjector.inject(
        "You are a helper.",
        {"lang": "Spanish"},
        cfg,
    )
    assert "About this user" in out
    assert "Spanish" in out


def test_memory_injector_skips_when_block_already_present():
    cfg = MemoryConfig(enabled=True, inject_into_prompt=True)
    existing = "## About this user\n- lang: Spanish"
    out = MemoryPromptInjector.inject(existing, {"lang": "French"}, cfg)
    assert out == existing


def test_summary_injector_appends_when_template_lacks_block():
    cfg = ContextSummaryConfig(summarize_on=0.8, inject_into_prompt=True)
    out = SummaryPromptInjector.inject("You are a helper.", "User asked about Q4.", cfg)
    assert "Conversation Summary" in out
    assert "Q4" in out


@pytest.mark.asyncio
async def test_context_summarizer_folds_oldest_turns():
    manager = SessionManager()
    session = await manager.create_session(agent_id="a", session_id="sum-sess")
    await manager.append_turn(
        "sum-sess",
        TurnRecord(
            turn_index=0,
            user_message="First question",
            llm_messages=[{"role": "assistant", "content": "First answer"}],
        ),
    )
    await manager.append_turn(
        "sum-sess",
        TurnRecord(
            turn_index=1,
            user_message="Second question",
            llm_messages=[{"role": "assistant", "content": "Second answer"}],
        ),
    )
    session = await manager.load_session("sum-sess")

    llm = MagicMock()
    llm.chat = AsyncMock(
        return_value=LLMResponse(
            content="Discussed first and second topics.",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="stop",
            raw_response={},
        )
    )
    summarizer = ContextSummarizer(
        ContextSummaryConfig(summarize_on=0.5, turns_to_fold=1),
        llm,
        manager,
    )
    await summarizer.summarize(session, 1)

    assert "first and second" in session.summary_text.lower()
    assert len(session.turns) == 1
    assert session.turns[0].turn_index == 1
    assert session.summary_through_turn == 0


def test_should_trigger_respects_ratio_and_disabled():
    session = AgentSession(
        session_id="s",
        agent_id="a",
        turns=[
            TurnRecord(
                turn_index=0,
                user_message="Hi",
                llm_messages=[{"role": "assistant", "content": "Hello"}],
            )
        ],
    )
    active = ContextSummarizer(
        ContextSummaryConfig(summarize_on=0.8),
        MagicMock(),
        MagicMock(),
    )
    disabled = ContextSummarizer(
        ContextSummaryConfig(summarize_on=None),
        MagicMock(),
        MagicMock(),
    )
    assert active.should_trigger(session, 9000, 10000) is True
    assert active.should_trigger(session, 5000, 10000) is False
    assert disabled.should_trigger(session, 9000, 10000) is False


@pytest.mark.asyncio
async def test_summary_text_in_system_prompt_via_builder():
    session = AgentSession(
        session_id="s",
        agent_id="a",
        summary_text="Prior discussion about revenue.",
    )
    agent = AgentConfig(
        name="a",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk"),
        context_summary=ContextSummaryConfig(summarize_on=0.8, inject_into_prompt=True),
    )
    messages = await ContextWindowBuilder().build(
        session,
        agent,
        current_user_message="Continue",
        summary_text=session.summary_text,
    )
    assert "Conversation Summary" in messages[0]["content"]
    assert "revenue" in messages[0]["content"]
