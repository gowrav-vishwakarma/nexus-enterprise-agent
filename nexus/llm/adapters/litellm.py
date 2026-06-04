"""LiteLLM adapter for the Nexus Agent Framework.

LiteLLM (https://litellm.ai) provides a unified OpenAI-compatible interface
to 100+ LLM providers. This adapter lets users route any provider string
through LiteLLM instead of — or alongside — the native provider adapters.

Usage examples in LLMProviderConfig:
    # Use LiteLLM as the routing layer for OpenAI
    LLMProviderConfig(provider="litellm", model="gpt-4o", api_key="sk-...")

    # Anthropic via LiteLLM (model prefix required)
    LLMProviderConfig(provider="litellm", model="anthropic/claude-3-5-sonnet-20241022")

    # Gemini via LiteLLM
    LLMProviderConfig(provider="litellm", model="gemini/gemini-2.0-flash-exp")

    # Groq via LiteLLM
    LLMProviderConfig(provider="litellm", model="groq/llama-3.1-70b-versatile")

    # Local Ollama via LiteLLM
    LLMProviderConfig(provider="litellm", model="ollama/llama3.2", base_url="http://localhost:11434")

    # Native provider shorthand (Nexus automatically prefixes if needed)
    LLMProviderConfig(provider="gemini", model="gemini-2.0-flash-exp", api_key="...")
"""

import json
import logging
from typing import Any, AsyncIterator, Optional

from nexus.config.llm import LLMProviderConfig, ProviderType
from nexus.llm.adapters.base import LLMAdapter
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest

logger = logging.getLogger(__name__)

# Providers that LiteLLM handles natively with a prefix in the model string
_LITELLM_PREFIX_MAP: dict[str, str] = {
    "anthropic": "anthropic",
    "gemini": "gemini",
    "groq": "groq",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "bedrock": "bedrock",
}


def build_litellm_model_string(provider: ProviderType, model: str) -> str:
    """Build the correct LiteLLM model identifier from a Nexus provider + model pair.

    - ``openai`` / ``azure_openai`` / ``litellm``: pass model as-is (LiteLLM default)
    - All others: prepend ``<provider>/`` unless the model string already contains it.
    """
    if provider in ("openai", "azure_openai", "litellm", "custom"):
        return model

    prefix = _LITELLM_PREFIX_MAP.get(provider, provider)
    expected_start = f"{prefix}/"
    if model.startswith(expected_start):
        return model
    return f"{expected_start}{model}"


class LiteLLMAdapter(LLMAdapter):
    """LLM adapter backed by LiteLLM for unified multi-provider access."""

    def __init__(self, config: LLMProviderConfig) -> None:
        super().__init__(config)
        try:
            import litellm as _ll  # noqa: F401
            self._litellm = _ll
        except ImportError as exc:
            raise ImportError(
                "litellm is required for the LiteLLMAdapter. "
                "Install it with: uv pip install litellm"
            ) from exc

        # Silence LiteLLM's verbose logging unless the user opts in
        self._litellm.suppress_debug_info = True
        self._litellm.set_verbose = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def _model(self) -> str:
        return build_litellm_model_string(self.config.provider, self.config.model)

    def _base_kwargs(
        self,
        temperature: Optional[float],
        max_tokens: Optional[int],
        stop_sequences: Optional[list[str]],
        tools: Optional[list[dict[str, Any]]],
        stream: bool = False,
    ) -> dict[str, Any]:
        """Assemble the common kwargs dict passed to litellm.acompletion."""
        kw: dict[str, Any] = {}

        api_key = self.config.get_api_key()
        if api_key:
            kw["api_key"] = api_key
        if self.config.base_url:
            kw["api_base"] = self.config.base_url
            # When using a custom api_base (e.g. LiteLLM proxy), pass the model
            # string EXACTLY as configured without letting LiteLLM strip provider
            # prefixes.  Force the OpenAI client so the full model name
            # (e.g. "openai/qwen") is sent unchanged to the endpoint.
            kw["model"] = self.config.model  # raw model, no prefix processing
            kw["custom_llm_provider"] = "openai"
        else:
            kw["model"] = self._model
        if self.config.api_version:
            kw["api_version"] = self.config.api_version
        if self.config.extra_headers:
            kw["extra_headers"] = self.config.extra_headers
        if temperature is not None:
            kw["temperature"] = temperature
        if max_tokens is not None:
            kw["max_tokens"] = max_tokens
        elif self.config.default_params.get("max_tokens"):
            kw["max_tokens"] = self.config.default_params["max_tokens"]
        if stop_sequences:
            kw["stop"] = stop_sequences
        if tools:
            kw["tools"] = tools
            kw["tool_choice"] = "auto"
        if stream:
            kw["stream"] = True

        # Merge any extra provider-specific params (won't overwrite above)
        for k, v in self.config.default_params.items():
            kw.setdefault(k, v)

        return kw

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCallRequest]:
        """Convert LiteLLM tool_call objects → Nexus ToolCallRequest list."""
        result: list[ToolCallRequest] = []
        if not raw_tool_calls:
            return result
        for tc in raw_tool_calls:
            try:
                args_str = tc.function.arguments or "{}"
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
                result.append(
                    ToolCallRequest(
                        id=tc.id or f"call_{len(result)}",
                        tool_name=tc.function.name or "",
                        tool_input=args,
                    )
                )
            except Exception as exc:
                logger.warning("Could not parse tool call from LiteLLM response: %s", exc)
        return result

    @staticmethod
    def _parse_usage(raw_usage: Any) -> TokenUsage:
        if raw_usage is None:
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=getattr(raw_usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(raw_usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(raw_usage, "total_tokens", 0) or 0,
            cached_tokens=getattr(raw_usage, "prompt_tokens_details", {}).get("cached_tokens", 0) if hasattr(raw_usage, "prompt_tokens_details") else 0,
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        """Convert a full LiteLLM ModelResponse → Nexus LLMResponse."""
        content: Optional[str] = None
        tool_calls: list[ToolCallRequest] = []
        finish_reason = "stop"

        if response.choices:
            choice = response.choices[0]
            finish_reason = choice.finish_reason or "stop"
            msg = choice.message
            content = getattr(msg, "content", None)
            tool_calls = self._parse_tool_calls(getattr(msg, "tool_calls", None))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=self._parse_usage(getattr(response, "usage", None)),
            finish_reason=finish_reason,
            raw_response={},  # avoid serialising the huge raw object
        )

    # ── Public interface ──────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Non-streaming chat via LiteLLM."""
        kw = self._base_kwargs(temperature, max_tokens, stop_sequences, tools)
        kw["messages"] = messages
        kw.update(kwargs)

        logger.debug("LiteLLMAdapter.chat → model=%s", self._model)
        try:
            response = await self._litellm.acompletion(**kw)
            return self._parse_response(response)
        except Exception as exc:
            logger.error("LiteLLM chat error (model=%s): %s", self._model, exc)
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Streaming chat via LiteLLM — yields LLMStreamChunk deltas."""
        kw = self._base_kwargs(temperature, max_tokens, stop_sequences, tools, stream=True)
        kw["messages"] = messages
        kw.update(kwargs)

        logger.debug("LiteLLMAdapter.chat_stream → model=%s", self._model)
        try:
            stream = await self._litellm.acompletion(**kw)
            async for chunk in stream:
                content_delta: Optional[str] = None
                tc_deltas: list[dict[str, Any]] = []
                finish_reason: Optional[str] = None
                usage: Optional[TokenUsage] = None

                if chunk.choices:
                    choice = chunk.choices[0]
                    delta = choice.delta
                    finish_reason = choice.finish_reason
                    content_delta = getattr(delta, "content", None)

                    raw_tcs = getattr(delta, "tool_calls", None)
                    if raw_tcs:
                        for tc in raw_tcs:
                            tc_deltas.append(
                                {
                                    "index": getattr(tc, "index", 0),
                                    "id": getattr(tc, "id", None),
                                    "function": {
                                        "name": getattr(tc.function, "name", None) if tc.function else None,
                                        "arguments": getattr(tc.function, "arguments", "") if tc.function else "",
                                    },
                                }
                            )

                raw_usage = getattr(chunk, "usage", None)
                if raw_usage:
                    usage = self._parse_usage(raw_usage)

                yield LLMStreamChunk(
                    content=content_delta,
                    tool_calls=tc_deltas,
                    finish_reason=finish_reason,
                    usage=usage,
                )
        except Exception as exc:
            logger.error("LiteLLM stream error (model=%s): %s", self._model, exc)
            raise
