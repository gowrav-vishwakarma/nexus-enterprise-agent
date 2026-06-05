"""Integration tests for skills in AgentRunner."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nexus.config import AgentConfig, LLMProviderConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.skills.config import SkillsConfig
from nexus.session.manager import SessionManager
from nexus.tools.registry import ToolRegistry
from nexus.llm.response import LLMResponse, TokenUsage

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


@pytest.mark.asyncio
async def test_runner_injects_skills_catalog():
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="skills-agent",
        llm=llm_config,
        skills=SkillsConfig(
            enabled=True,
            global_paths=[str(FIXTURES)],
            activation_mode="auto",
        ),
    )

    registry = ToolRegistry()
    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    response = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop",
        raw_response={},
    )

    captured_messages = []

    async def capture_chat(*, messages, tools=None):
        captured_messages.extend(messages)
        return response

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=capture_chat)):
        await runner.run(user_message="Hello", session_id="skills-sess-1")

    system_msg = captured_messages[0]
    assert system_msg["role"] == "system"
    assert "code-review" in system_msg["content"]
    assert "commit-messages" in system_msg["content"]
    assert "skills.load_skill" in system_msg["content"]


@pytest.mark.asyncio
async def test_runner_explicit_skills_injected():
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="skills-agent",
        llm=llm_config,
        skills=SkillsConfig(
            enabled=True,
            global_paths=[str(FIXTURES)],
            activation_mode="explicit",
            explicit_skills=["code-review"],
        ),
    )

    registry = ToolRegistry()
    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    response = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop",
        raw_response={},
    )

    captured_messages = []

    async def capture_chat(*, messages, tools=None):
        captured_messages.extend(messages)
        return response

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=capture_chat)):
        await runner.run(user_message="Hello", session_id="skills-sess-2")

    system_msg = captured_messages[0]
    assert "Active Skills" in system_msg["content"]
    assert "Read the code carefully" in system_msg["content"]
    assert "<skills>" not in system_msg["content"]


@pytest.mark.asyncio
async def test_runner_exposes_skills_tools():
    llm_config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key")
    agent_config = AgentConfig(
        name="skills-agent",
        llm=llm_config,
        skills=SkillsConfig(
            enabled=True,
            global_paths=[str(FIXTURES)],
            activation_mode="auto",
        ),
    )

    registry = ToolRegistry()
    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
    )

    response = LLMResponse(
        content="Done.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop",
        raw_response={},
    )

    captured_tools = []

    async def capture_chat(*, messages, tools=None):
        if tools:
            captured_tools.extend(tools)
        return response

    with patch.object(runner.llm_proxy, "chat", AsyncMock(side_effect=capture_chat)):
        await runner.run(user_message="Hello", session_id="skills-sess-3")

    tool_names = {t["name"] for t in captured_tools}
    assert "skills.load_skill" in tool_names
    assert "skills.read_skill_resource" in tool_names
    assert "skills.run_skill_script" not in tool_names
