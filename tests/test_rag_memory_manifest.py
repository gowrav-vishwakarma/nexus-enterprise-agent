"""YAML manifest + runner wiring for RAG and memory providers."""

from unittest.mock import AsyncMock, patch

import pytest

from nexus.config.agent import AgentConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import MemoryConfig
from nexus.llm.response import LLMResponse, TokenUsage, ToolCallRequest
from nexus.memory.cross_session_store import InMemoryCrossSessionMemoryStore
from nexus.rag.config import RAGConfig
from nexus.rag.embeddings import HashingEmbeddings
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry


def _agent(**kw) -> AgentConfig:
    return AgentConfig(
        name="rag-bot",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role="assistant", goal="answer"),
        **kw,
    )


def test_yaml_agent_accepts_rag_and_memory_provider():
    cfg = AgentConfig.model_validate(
        {
            "name": "docs",
            "llm": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"},
            "rag": {
                "provider": "in_memory",
                "collection": "handbook",
                "retrieval": {"k": 4, "hybrid": True},
            },
            "memory": {
                "enabled": True,
                "provider": "builtin_semantic",
                "require_approval": False,
            },
        }
    )
    assert cfg.rag is not None
    assert cfg.rag.collection == "handbook"
    assert cfg.rag.retrieval.hybrid is True
    assert cfg.memory.provider == "builtin_semantic"


def test_runner_builds_providers_from_config():
    store = InMemoryCrossSessionMemoryStore()
    runner = AgentRunner(
        config=_agent(
            rag=RAGConfig(provider="in_memory"),
            memory=MemoryConfig(enabled=True, provider="builtin_semantic", expose_tools=True),
        ),
        tool_registry=ToolRegistry(),
        run_context=RunContext(tenant_id="t", user_id="u"),
        cross_session_memory_store=store,
    )
    assert runner.rag_provider is not None
    assert runner.memory_provider is not None


def test_runner_skips_rag_when_unset():
    runner = AgentRunner(
        config=_agent(),
        tool_registry=ToolRegistry(),
        run_context=RunContext(tenant_id="t", user_id="u"),
    )
    assert runner.rag_provider is None


@pytest.mark.asyncio
async def test_runner_rag_retrieve_end_to_end():
    ctx = RunContext(tenant_id="acme", user_id="u1", session_id="s1")
    runner = AgentRunner(
        config=_agent(rag=RAGConfig(provider="in_memory")),
        tool_registry=ToolRegistry(),
        run_context=ctx,
    )
    await runner.rag_provider.ingest(
        ctx, ["The Eiffel Tower is in Paris, France."], collection="default"
    )
    response_turn_0 = LLMResponse(
        content="",
        tool_calls=[
            ToolCallRequest(
                id="call-1",
                tool_name="rag.retrieve",
                tool_input={"query": "Eiffel Tower", "k": 2},
            )
        ],
        usage=TokenUsage(),
        finish_reason="tool_calls",
        raw_response={},
    )
    response_turn_1 = LLMResponse(
        content="Paris.",
        tool_calls=[],
        usage=TokenUsage(),
        finish_reason="stop",
        raw_response={},
    )
    mock_chat = AsyncMock(side_effect=[response_turn_0, response_turn_1])
    with patch.object(runner.llm_proxy, "chat", mock_chat):
        result = await runner.run("Where is the Eiffel Tower?", session_id="s1")
    assert result.status == "completed"
    assert "rag.retrieve" in runner.tool_registry._tools
    assert result.final_response == "Paris."


@pytest.mark.asyncio
async def test_hashing_embeddings_stable():
    emb = HashingEmbeddings(dim=16)
    a = await emb.embed(["hello world"])
    b = await emb.embed(["hello world"])
    assert a == b
    assert len(a[0]) == 16
