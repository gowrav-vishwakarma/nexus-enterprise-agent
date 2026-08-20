"""Tests for the mountable FastAPI router in nexus[serve]."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from nexus.config.agent import AgentConfig  # noqa: E402
from nexus.config.llm import LLMProviderConfig  # noqa: E402
from nexus.llm.response import LLMResponse, TokenUsage  # noqa: E402
from nexus.runner.agent_runner import AgentRunner  # noqa: E402
from nexus.serve import AgentRouterConfig, create_agent_router  # noqa: E402
from nexus.session.manager import SessionManager  # noqa: E402
from nexus.tools.context import RunContext  # noqa: E402
from nexus.tools.registry import ToolRegistry  # noqa: E402


def _reply(content: str = "hi") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        finish_reason="stop",
        raw_response={},
    )


@pytest.fixture
def client_and_headers():
    """A mounted router whose RunContext is derived from request headers."""
    seen: dict = {}

    async def context_factory(request):
        seen["tenant"] = request.headers.get("x-tenant-id")
        return RunContext(tenant_id=seen["tenant"], user_id="u1")

    async def runner_factory(ctx: RunContext) -> AgentRunner:
        config = AgentConfig(
            name="serve-agent",
            llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key"),
        )
        runner = AgentRunner(
            config=config,
            tool_registry=ToolRegistry(),
            storage_config=SessionManager(),
            run_context=ctx,
        )
        runner.llm_proxy.chat = AsyncMock(return_value=_reply())
        return runner

    app = FastAPI()
    app.include_router(
        create_agent_router(
            runner_factory, context_factory, config=AgentRouterConfig(prefix="/v1")
        )
    )
    return TestClient(app), seen


def test_chat_endpoint_returns_result(client_and_headers):
    client, seen = client_and_headers

    response = client.post(
        "/v1/chat", json={"message": "hello"}, headers={"x-tenant-id": "acme"}
    )

    assert response.status_code == 200
    assert response.json()["final_response"] == "hi"


def test_context_factory_receives_the_real_request(client_and_headers):
    """Multi-tenant products read auth off the request; it must not arrive as None."""
    client, seen = client_and_headers

    client.post("/v1/chat", json={"message": "hello"}, headers={"x-tenant-id": "acme"})

    assert seen["tenant"] == "acme"


def test_chat_stream_endpoint_emits_sse(client_and_headers):
    client, _ = client_and_headers

    response = client.post(
        "/v1/chat/stream", json={"message": "hello"}, headers={"x-tenant-id": "acme"}
    )

    assert response.status_code == 200
    payloads = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert payloads, "expected at least one SSE event"
    assert all("seq" in (p.get("data") or {}) for p in payloads)


def test_unknown_session_returns_404(client_and_headers):
    client, _ = client_and_headers

    response = client.get("/v1/sessions/does-not-exist", headers={"x-tenant-id": "acme"})

    assert response.status_code == 404


def _sse_ids(text: str) -> list[int]:
    return [int(line[len("id: ") :]) for line in text.splitlines() if line.startswith("id: ")]


def test_stream_frames_carry_sse_ids_for_reconnect(client_and_headers):
    client, _ = client_and_headers

    response = client.post(
        "/v1/chat/stream",
        json={"message": "hello", "session_id": "s-replay"},
        headers={"x-tenant-id": "acme"},
    )

    ids = _sse_ids(response.text)
    assert ids == sorted(ids)
    assert ids[0] >= 1


def test_reattach_replays_only_events_after_last_event_id(client_and_headers):
    client, _ = client_and_headers
    first = client.post(
        "/v1/chat/stream",
        json={"message": "hello", "session_id": "s-replay"},
        headers={"x-tenant-id": "acme"},
    )
    ids = _sse_ids(first.text)

    reattached = client.get(
        "/v1/sessions/s-replay/stream",
        headers={"x-tenant-id": "acme", "Last-Event-ID": str(ids[0])},
    )

    assert reattached.status_code == 200
    assert _sse_ids(reattached.text) == ids[1:]


def test_reattach_is_scoped_to_the_tenant_that_ran_it(client_and_headers):
    """A buffered stream must not be readable by another tenant."""
    client, _ = client_and_headers
    client.post(
        "/v1/chat/stream",
        json={"message": "hello", "session_id": "s-replay"},
        headers={"x-tenant-id": "acme"},
    )

    other = client.get(
        "/v1/sessions/s-replay/stream", headers={"x-tenant-id": "globex"}
    )

    assert other.status_code == 404


def test_reattach_without_a_buffered_stream_returns_404(client_and_headers):
    client, _ = client_and_headers

    response = client.get("/v1/sessions/never-ran/stream", headers={"x-tenant-id": "acme"})

    assert response.status_code == 404


def test_require_auth_rejects_empty_identity():
    """require_auth is a no-op unless the factory returns a nameless context."""
    async def context_factory(_request):
        return RunContext()

    async def runner_factory(ctx: RunContext) -> AgentRunner:
        config = AgentConfig(
            name="serve-agent",
            llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key"),
        )
        runner = AgentRunner(
            config=config,
            tool_registry=ToolRegistry(),
            storage_config=SessionManager(),
            run_context=ctx,
        )
        runner.llm_proxy.chat = AsyncMock(return_value=_reply())
        return runner

    app = FastAPI()
    app.include_router(
        create_agent_router(
            runner_factory,
            context_factory,
            config=AgentRouterConfig(prefix="/v1", require_auth=True),
        )
    )
    client = TestClient(app)

    response = client.post("/v1/chat", json={"message": "hello"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_require_auth_allows_tenant_identity():
    async def context_factory(_request):
        return RunContext(tenant_id="acme")

    async def runner_factory(ctx: RunContext) -> AgentRunner:
        config = AgentConfig(
            name="serve-agent",
            llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-key"),
        )
        runner = AgentRunner(
            config=config,
            tool_registry=ToolRegistry(),
            storage_config=SessionManager(),
            run_context=ctx,
        )
        runner.llm_proxy.chat = AsyncMock(return_value=_reply())
        return runner

    app = FastAPI()
    app.include_router(
        create_agent_router(
            runner_factory,
            context_factory,
            config=AgentRouterConfig(prefix="/v1", require_auth=True),
        )
    )
    client = TestClient(app)

    response = client.post("/v1/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json()["final_response"] == "hi"
