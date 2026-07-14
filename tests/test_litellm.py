"""Tests for LiteLLM adapter model-string builder and proxy routing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.config.llm import LLMProviderConfig
from nexus.llm.adapters.litellm import LiteLLMAdapter, build_litellm_model_string
from nexus.llm.proxy import LLMProxy
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest
from nexus.llm.tool_format import format_openai_tools, tool_calls_to_openai_messages


# ── Model string builder ──────────────────────────────────────────────────────

@pytest.mark.parametrize("provider,model,expected", [
    # OpenAI — no prefix
    ("openai",       "gpt-4o",                          "gpt-4o"),
    ("azure_openai", "gpt-4o",                          "gpt-4o"),
    # litellm passthrough — no prefix
    ("litellm",      "anthropic/claude-3-5-sonnet",     "anthropic/claude-3-5-sonnet"),
    # Providers that get prefixed if missing
    ("anthropic",    "claude-3-5-sonnet-20241022",      "anthropic/claude-3-5-sonnet-20241022"),
    ("anthropic",    "anthropic/claude-3-5-sonnet-20241022", "anthropic/claude-3-5-sonnet-20241022"),  # no double-prefix
    ("gemini",       "gemini-2.0-flash-exp",            "gemini/gemini-2.0-flash-exp"),
    ("groq",         "llama-3.1-70b-versatile",         "groq/llama-3.1-70b-versatile"),
    ("ollama",       "llama3.2",                        "ollama/llama3.2"),
    ("openrouter",   "mistralai/mistral-7b-instruct",   "openrouter/mistralai/mistral-7b-instruct"),
    ("bedrock",      "anthropic.claude-3-sonnet",       "bedrock/anthropic.claude-3-sonnet"),
])
def test_build_litellm_model_string(provider, model, expected):
    assert build_litellm_model_string(provider, expected if "/" in expected and provider not in ("openai", "azure_openai", "litellm") else model) == expected or True
    # simpler direct assertion:
    result = build_litellm_model_string(provider, model)
    assert result == expected, f"Expected {expected!r}, got {result!r}"


# ── Proxy routing ─────────────────────────────────────────────────────────────

def test_proxy_routes_openai_to_native():
    """OpenAI provider should use the native OpenAIAdapter, not LiteLLM."""
    config = LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test")
    with patch("nexus.llm.adapters.openai.OpenAIAdapter.__init__", return_value=None):
        proxy = LLMProxy(config)
    from nexus.llm.adapters.openai import OpenAIAdapter
    assert isinstance(proxy._adapter, OpenAIAdapter)


def test_proxy_routes_anthropic_to_native():
    """Anthropic provider should use the native AnthropicAdapter, not LiteLLM."""
    config = LLMProviderConfig(provider="anthropic", model="claude-3-5-sonnet-20241022", api_key="sk-ant-test")
    with patch("nexus.llm.adapters.anthropic.AnthropicAdapter.__init__", return_value=None):
        proxy = LLMProxy(config)
    from nexus.llm.adapters.anthropic import AnthropicAdapter
    assert isinstance(proxy._adapter, AnthropicAdapter)


def test_proxy_routes_gemini_to_litellm():
    """Gemini (and other non-native providers) should route through LiteLLMAdapter."""
    config = LLMProviderConfig(provider="gemini", model="gemini-2.0-flash-exp", api_key="gm-key")
    proxy = LLMProxy(config)
    assert isinstance(proxy._adapter, LiteLLMAdapter)
    # Model string should be auto-prefixed
    assert proxy._adapter._model == "gemini/gemini-2.0-flash-exp"


def test_proxy_routes_openai_with_base_url_to_native():
    """provider=openai with base_url still uses OpenAIAdapter (provider selects adapter)."""
    config = LLMProviderConfig(
        provider="openai",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    with patch("nexus.llm.adapters.openai.OpenAIAdapter.__init__", return_value=None):
        proxy = LLMProxy(config)
    from nexus.llm.adapters.openai import OpenAIAdapter
    assert isinstance(proxy._adapter, OpenAIAdapter)


def test_proxy_routes_litellm_with_base_url_to_litellm():
    """provider=litellm with base_url uses LiteLLMAdapter with OpenAI proxy delegate."""
    config = LLMProviderConfig(
        provider="litellm",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    proxy = LLMProxy(config)
    assert isinstance(proxy._adapter, LiteLLMAdapter)
    assert proxy._adapter._proxy_delegate is not None
    assert proxy._adapter._proxy_delegate.config.model == "openai/qwen"


@pytest.mark.asyncio
async def test_litellm_adapter_proxy_passes_model_unchanged():
    """With base_url set, chat delegates to OpenAI SDK — model not stripped to qwen."""
    config = LLMProviderConfig(
        provider="litellm",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    mock_response = LLMResponse(content="ok")
    adapter._proxy_delegate.chat = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

    result = await adapter.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    adapter._proxy_delegate.chat.assert_awaited_once()  # type: ignore[attr-defined]
    assert adapter._proxy_delegate.config.model == "openai/qwen"


def test_proxy_routes_litellm_provider_to_litellm():
    """Explicit litellm provider should use LiteLLMAdapter with model as-is."""
    config = LLMProviderConfig(
        provider="litellm",
        model="anthropic/claude-3-5-sonnet-20241022",
        api_key="sk-ant-test",
    )
    proxy = LLMProxy(config)
    assert isinstance(proxy._adapter, LiteLLMAdapter)
    assert proxy._adapter._model == "anthropic/claude-3-5-sonnet-20241022"


# ── LiteLLM adapter chat (mocked) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_litellm_adapter_chat_mocked():
    """Verify LiteLLMAdapter correctly parses a mocked litellm response."""
    config = LLMProviderConfig(provider="gemini", model="gemini-2.0-flash-exp", api_key="gm-key")
    adapter = LiteLLMAdapter(config)

    # Build a mock response that mimics the litellm ModelResponse structure
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
    assert result.usage.completion_tokens == 5
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_litellm_adapter_chat_with_tool_calls():
    """Verify tool call parsing from a mocked LiteLLM response."""
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
    """LiteLLMAdapter must pass OpenAI-shaped tools to acompletion."""
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
    """ToolCallRequest list serializes to OpenAI assistant tool_calls shape."""
    tcs = [
        ToolCallRequest(
            id="call_1",
            tool_name="calendar.get_events",
            tool_input={},
        )
    ]
    serialized = tool_calls_to_openai_messages(tcs)
    assert serialized[0]["type"] == "function"
    assert serialized[0]["function"]["name"] == "calendar.get_events"
    assert serialized[0]["function"]["arguments"] == "{}"


# ── Streaming via OpenAI proxy delegate (base_url path) ───────────────────────

@pytest.mark.asyncio
async def test_litellm_proxy_delegate_chat_stream_async_gen():
    """litellm+base_url must iterate OpenAI-delegate async generators."""
    config = LLMProviderConfig(
        provider="litellm",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    assert adapter._proxy_delegate is not None

    async def fake_stream(*_a, **_k):
        yield LLMStreamChunk(content="Namaste")
        yield LLMStreamChunk(content=None, finish_reason="stop")

    adapter._proxy_delegate.chat_stream = fake_stream  # type: ignore[method-assign]

    chunks = [
        c async for c in adapter.chat_stream(messages=[{"role": "user", "content": "hi"}])
    ]
    assert [c.content for c in chunks if c.content] == ["Namaste"]
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_litellm_proxy_delegate_chat_stream_legacy_coro():
    """Regression: delegate that returns a coroutine-wrapped iterator still works."""
    config = LLMProviderConfig(
        provider="litellm",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)

    async def legacy_chat_stream(*_a, **_k):
        async def gen():
            yield LLMStreamChunk(content="ok")
            yield LLMStreamChunk(finish_reason="stop")

        return gen()

    adapter._proxy_delegate.chat_stream = legacy_chat_stream  # type: ignore[method-assign]

    chunks = [
        c async for c in adapter.chat_stream(messages=[{"role": "user", "content": "hi"}])
    ]
    assert chunks[0].content == "ok"


@pytest.mark.asyncio
async def test_openai_proxy_disables_reasoning_for_qwen():
    """Proxy-hosted Qwen must disable thinking so content is speakable."""
    from nexus.llm.adapters.openai import OpenAIAdapter

    config = LLMProviderConfig(
        provider="openai",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = OpenAIAdapter(config)
    params: dict = {"model": "openai/qwen", "messages": []}
    adapter._apply_proxy_defaults(params)
    assert params["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.asyncio
async def test_litellm_proxy_delegate_chat_stream_maps_stop_sequences():
    """OpenAI delegate must map stop_sequences → stop for streaming calls."""
    from unittest.mock import AsyncMock, MagicMock

    config = LLMProviderConfig(
        provider="litellm",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://localhost:4000",
    )
    adapter = LiteLLMAdapter(config)
    delegate = adapter._proxy_delegate
    assert delegate is not None

    mock_stream = MagicMock()

    async def _aiter():
        yield MagicMock(choices=[])

    mock_stream.__aiter__ = lambda self: _aiter()
    delegate._async_client = MagicMock()
    delegate._async_client.chat.completions.create = AsyncMock(return_value=mock_stream)

    async for _ in adapter.chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        stop_sequences=["END"],
    ):
        pass

    call_kwargs = delegate._async_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["stop"] == ["END"]
    assert "stop_sequences" not in call_kwargs


@pytest.mark.asyncio
async def test_agent_runner_litellm_proxy_stream_e2e():
    """Full AgentRunner path: litellm+base_url → OpenAI delegate → streamed reply."""
    from nexus.config.agent import AgentConfig
    from nexus.runner.agent_runner import AgentRunner
    from nexus.session.manager import SessionManager

    config = LLMProviderConfig(
        provider="litellm",
        model="openai/qwen",
        api_key="sk-test",
        base_url="http://45.194.3.236:4000/",
    )
    from nexus.tools.registry import ToolRegistry

    runner = AgentRunner(
        AgentConfig(name="voice_grpc", llm=config),
        tool_registry=ToolRegistry(),
        storage_config=SessionManager(),
    )
    adapter = runner.llm_proxy._adapter
    assert isinstance(adapter, LiteLLMAdapter)
    assert adapter._proxy_delegate is not None

    async def fake_stream(*_a, **_k):
        yield LLMStreamChunk(content="Hello")
        yield LLMStreamChunk(content=".")
        yield LLMStreamChunk(
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )

    adapter._proxy_delegate.chat_stream = fake_stream  # type: ignore[method-assign]

    events = [ev async for ev in runner.run_stream("halod", stream=True)]
    types = [e.event_type for e in events]
    assert "error" not in types
    assert "final_response" in types
    final = next(e for e in events if e.event_type == "final_response")
    assert final.content == "Hello."
