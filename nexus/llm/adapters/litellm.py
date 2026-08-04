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

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

from nexus.config.llm import LLMProviderConfig, ProviderType
from nexus.errors import classify_litellm_error
from nexus.llm.adapters.base import LLMAdapter
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage, ToolCallRequest
from nexus.llm.tool_format import format_openai_tools
from nexus.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

# Known provider prefixes that LiteLLM understands
_PROVIDER_PREFIXES = (
    "openai/", "azure_openai/", "anthropic/", "gemini/",
    "ollama/", "groq/", "openrouter/", "bedrock/",
)


def has_provider_prefix(model: str) -> bool:
    """Check if model string starts with a known provider prefix."""
    return any(model.startswith(prefix) for prefix in _PROVIDER_PREFIXES)


def strip_provider_prefix(model: str) -> str:
    """Strip provider prefix from model string. E.g., 'openai/qwen' -> 'qwen'."""
    for prefix in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


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

        # Reasoning switches (``thinking``, ``reasoning_effort``, ``extra_body``) are
        # set per-deployment in default_params but are not accepted by every model.
        # Let LiteLLM drop unsupported params instead of failing the whole request.
        self._litellm.drop_params = True

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def _model(self) -> str:
        """Model string sent to litellm.

        Without ``base_url``, use normal per-provider prefixing (``gemini/…``,
        ``ollama/…``, etc.).

        With ``base_url`` (LiteLLM proxy, vLLM, SGLang, LM Studio), the env/manifest
        model is the **exact name registered on your server** (e.g. ``openai/qwen``).
        We only prepend ``litellm_proxy/`` when needed — that is litellm's required
        transport prefix for proxy calls, not a rename. Without it, litellm strips
        ``openai/`` and the proxy receives ``qwen`` instead of ``openai/qwen``.
        """
        raw = self.config.model
        if self.config.base_url:
            if raw.startswith("litellm_proxy/"):
                return raw
            return f"litellm_proxy/{raw}"
        return build_litellm_model_string(self.config.provider, raw)

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
        kw["model"] = self._model
        if self.config.base_url:
            kw["api_base"] = self.config.base_url
        if self.config.api_version:
            kw["api_version"] = self.config.api_version
        if self.config.extra_headers:
            kw["extra_headers"] = dict(self.config.extra_headers)
        if temperature is not None:
            kw["temperature"] = temperature
        if max_tokens is not None:
            kw["max_tokens"] = max_tokens
        elif self.config.default_params.get("max_tokens"):
            kw["max_tokens"] = self.config.default_params["max_tokens"]
        if stop_sequences:
            kw["stop"] = stop_sequences
        if tools:
            kw["tools"] = format_openai_tools(tools)
            kw["tool_choice"] = "auto"
        if stream:
            kw["stream"] = True

        # Merge any extra provider-specific params (won't overwrite above).
        # This is where users pass extra_body / chat_template_kwargs / reasoning
        # switches from the manifest's default_params.
        for k, v in self.config.default_params.items():
            kw.setdefault(k, v)

        self._apply_thinking_switch(kw)
        return kw

    def _apply_thinking_switch(self, kw: dict[str, Any]) -> None:
        """Turn a self-hosted model's reasoning on or off when explicitly configured.

        Only acts when ``config.enable_thinking`` is set. Left at ``None`` (the
        default) the model's own setting applies, so reasoning-capable deployments
        stream ``reasoning_content`` normally.

        Voice pipelines should set ``enable_thinking=False``: a ``<think>…</think>``
        block before any speakable text wrecks time-to-first-audio. Anything already
        in ``default_params.extra_body`` wins.
        """
        if self.config.enable_thinking is None:
            return
        extra = dict(kw.get("extra_body") or {})
        template_kwargs = dict(extra.get("chat_template_kwargs") or {})
        template_kwargs.setdefault("enable_thinking", self.config.enable_thinking)
        extra["chat_template_kwargs"] = template_kwargs
        kw["extra_body"] = extra

    @staticmethod
    def _read_reasoning(obj: Any) -> Optional[str]:
        """Read reasoning text off a LiteLLM delta or message.

        LiteLLM standardises reasoning as ``reasoning_content``, but some
        OpenAI-compatible proxies use the shorter ``reasoning``, so check both.
        """
        for attr in ("reasoning_content", "reasoning"):
            value = getattr(obj, attr, None)
            if value:
                return str(value)
        return None

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
        cached = 0
        details = getattr(raw_usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        return TokenUsage(
            prompt_tokens=getattr(raw_usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(raw_usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(raw_usage, "total_tokens", 0) or 0,
            cached_tokens=cached,
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        """Convert a full LiteLLM ModelResponse → Nexus LLMResponse."""
        content: Optional[str] = None
        reasoning: Optional[str] = None
        tool_calls: list[ToolCallRequest] = []
        finish_reason = "stop"

        if response.choices:
            choice = response.choices[0]
            finish_reason = choice.finish_reason or "stop"
            msg = choice.message
            content = getattr(msg, "content", None)
            reasoning = self._read_reasoning(msg)
            tool_calls = self._parse_tool_calls(getattr(msg, "tool_calls", None))

        return LLMResponse(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            usage=self._parse_usage(getattr(response, "usage", None)),
            finish_reason=finish_reason,
            raw_response={},  # avoid serialising the huge raw object
        )

    # ── Public interface ──────────────────────────────────────────────────────

    async def _acompletion_with_timeout(self, **kw: Any) -> Any:
        """Call litellm.acompletion with configured timeout."""
        timeout = self.config.timeout
        if timeout and timeout > 0:
            return await asyncio.wait_for(
                self._litellm.acompletion(**kw),
                timeout=timeout,
            )
        return await self._litellm.acompletion(**kw)

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

        async def _call() -> LLMResponse:
            response = await self._acompletion_with_timeout(**kw)
            return self._parse_response(response)

        try:
            if self.config.max_retries > 0:
                return await retry_with_backoff(
                    _call,
                    max_retries=self.config.max_retries,
                    base_delay=self.config.retry_delay,
                    retry_on=(Exception,),
                )
            return await _call()
        except Exception as exc:
            logger.error("LiteLLM chat error (model=%s): %s", self._model, exc)
            raise classify_litellm_error(exc) from exc

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
        kwargs.pop("stop_sequences", None)
        kw.update(kwargs)

        logger.debug("LiteLLMAdapter.chat_stream → model=%s", self._model)
        try:
            if self.config.timeout and self.config.timeout > 0:
                stream = await asyncio.wait_for(
                    self._litellm.acompletion(**kw),
                    timeout=self.config.timeout,
                )
            else:
                stream = await self._litellm.acompletion(**kw)
            async for chunk in stream:
                content_delta: Optional[str] = None
                reasoning_delta: Optional[str] = None
                tc_deltas: list[dict[str, Any]] = []
                finish_reason: Optional[str] = None
                usage: Optional[TokenUsage] = None

                if chunk.choices:
                    choice = chunk.choices[0]
                    delta = choice.delta
                    finish_reason = choice.finish_reason
                    content_delta = getattr(delta, "content", None)
                    reasoning_delta = self._read_reasoning(delta)

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
                    reasoning=reasoning_delta,
                    tool_calls=tc_deltas,
                    finish_reason=finish_reason,
                    usage=usage,
                )
        except Exception as exc:
            logger.error("LiteLLM stream error (model=%s): %s", self._model, exc)
            raise classify_litellm_error(exc) from exc
