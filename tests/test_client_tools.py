"""Client tools and elicitations: pause, stream, and resume.

These cover the flow products use for browser-side actions (a Vue app running a
tool in an iframe) and for asking the user a question mid-run. The run must
pause without executing the tool server-side, surface the pending interaction,
and continue once the client sends a result back.
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, patch

from nexus.config.agent import AgentConfig, TurnConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

SERVER_RAN: list[str] = []


@tool(name="fill_form", execution="client")
def fill_form(field: str) -> str:
    """Browser-side action; the server stub must never run."""
    SERVER_RAN.append("fill_form")
    return "server-side execution should not happen"


@tool(name="request_user_input", execution="client")
def request_user_input(question: str) -> str:
    """Ask the user a question and wait for their answer."""
    SERVER_RAN.append("request_user_input")
    return ""


@tool(name="slow_client_action", execution="client", timeout_seconds=1)
async def slow_client_action(field: str) -> str:
    await asyncio.sleep(5)
    return "should never run"


def _reply(content: str = "", tool_calls=None) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="tool_calls" if tool_calls else "stop",
        raw_response={},
    )


def _call(tool_name: str, **args) -> ToolCallRequest:
    return ToolCallRequest(id=f"call-{tool_name}", tool_name=tool_name, tool_input=args)


@pytest.fixture(autouse=True)
def _reset_server_ran():
    SERVER_RAN.clear()
    yield
    SERVER_RAN.clear()


@pytest.fixture
def runner_and_manager():
    registry = ToolRegistry()
    registry.add_tool(fill_form)
    registry.add_tool(request_user_input)
    registry.add_tool(slow_client_action)

    manager = SessionManager()
    config = AgentConfig(
        name="client-tool-agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key"),
        turns=TurnConfig(max_turns=5),
    )
    return (
        AgentRunner(config=config, tool_registry=registry, storage_config=manager),
        manager,
    )


@pytest.mark.asyncio
async def test_client_tool_pauses_without_running_server_side(runner_and_manager):
    runner, _ = runner_and_manager
    mock_chat = AsyncMock(side_effect=[_reply("opening the form", [_call("fill_form", field="name")])])

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run(user_message="fill the form", session_id="client-1")

    assert result.status == "paused"
    assert SERVER_RAN == [], "a client tool must not execute on the server"
    pending = result.pending_interactions
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "fill_form"
    assert pending[0]["kind"] == "client_tool"
    assert pending[0]["args"] == {"field": "name"}


@pytest.mark.asyncio
async def test_elicitation_pauses_with_its_own_kind(runner_and_manager):
    runner, _ = runner_and_manager
    mock_chat = AsyncMock(
        side_effect=[_reply("", [_call("request_user_input", question="Which invoice?")])]
    )

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run(user_message="pay it", session_id="client-2")

    assert result.status == "paused"
    assert result.pending_interactions[0]["kind"] == "elicitation"
    assert result.pending_interactions[0]["args"]["question"] == "Which invoice?"


@pytest.mark.asyncio
async def test_declared_timeout_does_not_cancel_a_client_tool(runner_and_manager):
    """A client tool pauses before execution, so its timeout never applies."""
    runner, _ = runner_and_manager
    mock_chat = AsyncMock(
        side_effect=[_reply("", [_call("slow_client_action", field="x")])]
    )

    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await asyncio.wait_for(
            runner.run(user_message="go", session_id="client-3"), timeout=3
        )

    assert result.status == "paused"


@pytest.mark.asyncio
async def test_resume_feeds_the_client_result_back_to_the_model(runner_and_manager):
    runner, _ = runner_and_manager
    first = AsyncMock(side_effect=[_reply("", [_call("fill_form", field="name")])])

    with patch.object(runner.llm_proxy, "chat", first):
        paused = await runner.run(user_message="fill it", session_id="client-4")

    tc_id = paused.pending_interactions[0]["tc_id"]
    second = AsyncMock(side_effect=[_reply("All done.")])

    with patch.object(runner.llm_proxy, "chat", second):
        resumed = await runner.resume(
            "client-4", results=[{"tc_id": tc_id, "content": "form filled by user"}]
        )

    assert resumed.status == "completed"
    assert resumed.final_response == "All done."

    sent_messages = second.await_args.kwargs.get("messages") or second.await_args.args[0]
    rendered = str(sent_messages)
    assert "form filled by user" in rendered, "client result must reach the model"


@pytest.mark.asyncio
async def test_streaming_client_tool_emits_paused_with_pending_interactions(
    runner_and_manager,
):
    """Products map this event to their own clarification/tool payloads."""
    runner, _ = runner_and_manager

    async def chat_stream(messages=None, *args, **kwargs):
        async def gen():
            yield LLMStreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call-1",
                        "name": "request_user_input",
                        "arguments": '{"question": "Which one?"}',
                    }
                ],
            )
            yield LLMStreamChunk(finish_reason="tool_calls", usage=TokenUsage())

        return gen()

    with patch.object(runner.llm_proxy, "chat_stream", chat_stream):
        events = [
            e
            async for e in runner.run_stream(
                user_message="go", session_id="client-5", stream=True
            )
        ]

    paused = [e for e in events if e.event_type == "paused"]
    assert paused, "streaming run must emit a paused event"
    pending = paused[0].data["pending_interactions"]
    assert pending[0]["tool_name"] == "request_user_input"
    assert pending[0]["args"]["question"] == "Which one?"
    assert all("seq" in (e.data or {}) for e in events)
