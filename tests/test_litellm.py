"""Tests for the unified LiteLLM adapter (model routing, proxy pass-through, streaming)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.config.llm import LLMProviderConfig
from nexus.llm.adapters.litellm import LiteLLMAdapter, build_litellm_model_string
from nexus.llm.proxy import LLMProxy
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest
from nexus.llm.tool_format import format_openai_tools, tool_calls_to_openai_messages


# ── Model string builder ──────────────────────────────────────────────────────

@pytest.mark.parametrize("provider,model,expected", [
    ("openai",       "gpt-4o",                          "gpt-4o"),
    ("azure_openai", "gpt-4o",                          "gpt-4o"),
    ("litellm",      "anthropic/claude-3-5-sonnet",     "anthropic/claude-3-5-sonnet"),
    ("anthropic",    "claude-3-5-sonnet-20241022",      "anthropic/claude-3-5-sonnet-20241022"),
    ("anthropic",    "anthropic/claude-3-5-sonnet-20241022", "anthropic/claude-3-5-sonnet-20241022"),
    ("gemini",       "gemini-2.0-flash-exp",            "gemini/gemini-2.0-flash-exp"),
    ("groq",         "llama-3.1-70b-versatile",         "groq/llama-3.1-70b-versatile"),
    ("ollama",       "llama3.2",                        "ollama/llama3.2"),
    ("openrouter",   "mistralai/mistral-7b-instruct",   "openrouter/mistralai/mistral-7b-instruct"),
    ("bedrock",      "anthropic.claude-3-sonnet",       "bedrock/anthropic.claude-3-sonnet"),
])
def test_build_litellm_model_string(provider, model, expected):
    assert build_litellm_model_string(provider, model) == expected


# ── Proxy routing: everything goes through the LiteLLM adapter ─────────────────

@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai", "gpt-4o"),
        ("azure_openai", "gpt-4o"),
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("gemini", "gemini-2.0-flash-exp"),
        ("groq", "llama-3.1-70b-versatile"),
        ("ollama", "llama3.2"),
        ("litellm", "anthropic/claude-3-5-sonnet-20241022"),
    ],
)
def test_all_providers_route_to_litellm(provider, model):
    config = LLMProviderConfig(provider=provider, model=model, api_key="k")
    proxy = LLMProxy(config)
    assert isinstance(proxy._adapter, LiteLLMAdapter)


def test_gemini_model_string_is_prefixed():
    config = LLMProviderConfig(provider="gemini", model="gemini-2.0-flash-exp", api_key="gm-key")
    adapter = LiteLLMAdapter(config)
    assert adapter._model == "gemini/gemini-2.0-flash-exp"


# ── Self-hosted proxy pass-through (base_url set) ──────────────────────────────

def test_proxy_base_url_preserves_registered_model_name():
    """Env model ``openai/qwen`` must reach the proxy as ``openai/qwen``, not ``qwen``.

    litellm requires a ``litellm_proxy/`` transport prefix when ``api_base`` is set;
    Nexus adds it automatically — the user's env value stays unchanged.
    """
    config = LLMProviderConfig(
        provider="litellm",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    kw = adapter._base_kwargs(None, None, None, None)
    assert kw["model"] == "litellm_proxy/openai/qwen"
    assert "custom_llm_provider" not in kw
    assert kw["api_base"] == "http://localhost:4000"


def test_proxy_model_already_prefixed_is_not_doubled():
    config = LLMProviderConfig(
        provider="litellm",
        model="litellm_proxy/openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    assert adapter._model == "litellm_proxy/openai/qwen"


def test_proxy_azure_uses_litellm_proxy_prefix():
    config = LLMProviderConfig(
        provider="azure_openai",
        model="my-deployment",
        api_key="k",
        base_url="https://my.openai.azure.com",
        api_version="2024-06-01",
    )
    adapter = LiteLLMAdapter(config)
    kw = adapter._base_kwargs(None, None, None, None)
    assert kw["model"] == "litellm_proxy/my-deployment"


def test_proxy_disables_reasoning_by_default():
    config = LLMProviderConfig(
        provider="litellm",
        model="ollama/qwen3:4b",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    kw = adapter._base_kwargs(None, None, None, None)
    assert kw["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert kw["model"] == "litellm_proxy/ollama/qwen3:4b"
    assert "custom_llm_provider" not in kw


def test_manifest_extra_body_overrides_reasoning_default():
    """default_params.extra_body from the manifest wins over the auto-default."""
    config = LLMProviderConfig(
        provider="litellm",
        model="ollama/qwen3:4b",
        api_key="sk-test",
        base_url="http://localhost:4000",
        default_params={"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}},
    )
    adapter = LiteLLMAdapter(config)
    kw = adapter._base_kwargs(None, None, None, None)
    assert kw["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_extra_headers_forwarded():
    config = LLMProviderConfig(
        provider="litellm",
        model="ollama/qwen3:4b",
        api_key="sk-test",
        base_url="http://localhost:4000",
        extra_headers={"x-route": "voice"},
    )
    adapter = LiteLLMAdapter(config)
    kw = adapter._base_kwargs(None, None, None, None)
    assert kw["extra_headers"]["x-route"] == "voice"


def test_direct_openai_has_no_proxy_tuning():
    """No base_url → normal litellm routing, no custom provider, no reasoning inject."""
    config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk")
    adapter = LiteLLMAdapter(config)
    kw = adapter._base_kwargs(None, None, None, None)
    assert kw["model"] == "gpt-4o"
    assert "custom_llm_provider" not in kw
    assert "extra_body" not in kw


# ── chat() parsing (mocked acompletion) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_litellm_adapter_chat_mocked():
    config = LLMProviderConfig(provider="gemini", model="gemini-2.0-flash-exp", api_key="gm-key")
    adapter = LiteLLMAdapter(config)

    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = "Hello from Gemini!"
    mock_choice.message.tool_calls = None

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 12
    mock_response.usage.completion_tokens = 5
    mock_response.usage.total_tokens = 17

    adapter._litellm = MagicMock()
    adapter._litellm.acompletion = AsyncMock(return_value=mock_response)

    result = await adapter.chat(messages=[{"role": "user", "content": "Hi"}])

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello from Gemini!"
    assert result.tool_calls == []
    assert result.usage.prompt_tokens == 12
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_litellm_adapter_chat_with_tool_calls():
    import json
    config = LLMProviderConfig(provider="litellm", model="gpt-4o", api_key="sk-test")
    adapter = LiteLLMAdapter(config)

    mock_tc = MagicMock()
    mock_tc.id = "call_abc123"
    mock_tc.function.name = "web_search"
    mock_tc.function.arguments = json.dumps({"query": "Nexus agent framework"})

    mock_choice = MagicMock()
    mock_choice.finish_reason = "tool_calls"
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [mock_tc]

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 20
    mock_response.usage.completion_tokens = 10
    mock_response.usage.total_tokens = 30

    adapter._litellm = MagicMock()
    adapter._litellm.acompletion = AsyncMock(return_value=mock_response)

    result = await adapter.chat(messages=[{"role": "user", "content": "Search for something"}])

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_abc123"
    assert result.tool_calls[0].tool_name == "web_search"
    assert result.tool_calls[0].tool_input == {"query": "Nexus agent framework"}


@pytest.mark.asyncio
async def test_litellm_adapter_wraps_tools():
    config = LLMProviderConfig(provider="gemini", model="gemini-2.0-flash-exp", api_key="gm-key")
    adapter = LiteLLMAdapter(config)

    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = "ok"
    mock_choice.message.tool_calls = None
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    adapter._litellm = MagicMock()
    adapter._litellm.acompletion = AsyncMock(return_value=mock_response)

    registry_tools = [
        {
            "name": "calendar.get_events",
            "description": "Get events",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    await adapter.chat(messages=[{"role": "user", "content": "Hi"}], tools=registry_tools)

    call_kwargs = adapter._litellm.acompletion.call_args.kwargs
    assert call_kwargs["tools"] == format_openai_tools(registry_tools)
    assert call_kwargs["tools"][0]["type"] == "function"
    assert call_kwargs["tools"][0]["function"]["name"] == "calendar.get_events"


def test_tool_calls_openai_serialization():
    tcs = [ToolCallRequest(id="call_1", tool_name="calendar.get_events", tool_input={})]
    serialized = tool_calls_to_openai_messages(tcs)
    assert serialized[0]["type"] == "function"
    assert serialized[0]["function"]["name"] == "calendar.get_events"
    assert serialized[0]["function"]["arguments"] == "{}"


# ── Streaming ─────────────────────────────────────────────────────────────────

def _stream_chunk(content=None, finish_reason=None):
    chunk = MagicMock()
    chunk.choices = [MagicMock(delta=MagicMock(content=content, tool_calls=None), finish_reason=finish_reason)]
    chunk.usage = None
    return chunk


def _fake_acompletion(chunks, captured=None):
    async def acompletion(**kw):
        if captured is not None:
            captured.update(kw)

        async def gen():
            for c in chunks:
                yield c

        return gen()

    return acompletion


@pytest.mark.asyncio
async def test_chat_stream_yields_content_and_finish():
    config = LLMProviderConfig(
        provider="litellm", model="ollama/qwen3:4b", api_key="k",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    adapter._litellm = MagicMock()
    adapter._litellm.acompletion = _fake_acompletion(
        [_stream_chunk("Namaste"), _stream_chunk(finish_reason="stop")]
    )

    chunks = [c async for c in adapter.chat_stream(messages=[{"role": "user", "content": "hi"}])]
    assert [c.content for c in chunks if c.content] == ["Namaste"]
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_chat_stream_maps_stop_sequences():
    config = LLMProviderConfig(
        provider="litellm", model="ollama/qwen3:4b", api_key="k",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    captured: dict = {}
    adapter._litellm = MagicMock()
    adapter._litellm.acompletion = _fake_acompletion([_stream_chunk(finish_reason="stop")], captured)

    async for _ in adapter.chat_stream(
        messages=[{"role": "user", "content": "hi"}], stop_sequences=["END"]
    ):
        pass

    assert captured["stop"] == ["END"]
    assert "stop_sequences" not in captured


@pytest.mark.asyncio
async def test_agent_runner_litellm_proxy_stream_e2e():
    """Full AgentRunner path: litellm+base_url → streamed reply, no errors."""
    from nexus.config.agent import AgentConfig
    from nexus.runner.agent_runner import AgentRunner
    from nexus.session.manager import SessionManager
    from nexus.tools.registry import ToolRegistry

    config = LLMProviderConfig(
        provider="litellm",
        model="ollama/qwen3:4b",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    runner = AgentRunner(
        AgentConfig(name="voice_grpc", llm=config),
        tool_registry=ToolRegistry(),
        storage_config=SessionManager(),
    )
    adapter = runner.llm_proxy._adapter
    assert isinstance(adapter, LiteLLMAdapter)

    async def fake_stream(*_a, **_k):
        yield LLMStreamChunk(content="Hello")
        yield LLMStreamChunk(content=".")
        yield LLMStreamChunk(
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )

    adapter.chat_stream = fake_stream  # type: ignore[method-assign]

    events = [ev async for ev in runner.run_stream("halod", stream=True)]
    types = [e.event_type for e in events]
    assert "error" not in types
    assert "final_response" in types
    final = next(e for e in events if e.event_type == "final_response")
    assert final.content == "Hello."
