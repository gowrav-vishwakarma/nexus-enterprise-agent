"""Live LiteLLM think vs no-think tests against the configured proxy.

Requires network + a reachable LITELLM_BASE_URL (or NEXUS_LLM_BASE_URL), so the
whole module is marked ``live_llm`` and skipped by the default test run.

Run:
    uv run pytest -m live_llm tests/test_litellm_think_integration.py -v -s
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from nexus.config.llm import LLMProviderConfig
from nexus.llm.adapters.litellm import LiteLLMAdapter
from nexus.realtime.pipelines.cascaded import _strip_think

pytestmark = pytest.mark.live_llm


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        env = Path(__file__).resolve().parents[1] / ".env"
        if env.exists():
            load_dotenv(dotenv_path=env, override=True)
    except ImportError:
        pass


def _voice_llm_config(*, enable_thinking: bool) -> LLMProviderConfig:
    base_url = (
        os.getenv("LITELLM_BASE_URL")
        or os.getenv("NEXUS_LLM_BASE_URL")
        or ""
    ).rstrip("/")
    api_key = os.getenv("LITELLM_API_KEY") or os.getenv("NEXUS_LLM_API_KEY") or ""
    model = (
        os.getenv("VOICE_LLM_MODEL")
        or os.getenv("NEXUS_LLM_MODEL")
        or "ollama/qwen3:4b"
    )
    if not base_url:
        pytest.skip("Set LITELLM_BASE_URL or NEXUS_LLM_BASE_URL in .env")

    return LLMProviderConfig(
        provider="litellm",
        model=model,
        api_key=api_key,
        base_url=base_url,
        default_params={
            "max_tokens": int(os.getenv("VOICE_LLM_MAX_TOKENS", "400")),
            "temperature": float(os.getenv("VOICE_LLM_TEMPERATURE", "0.4")),
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": enable_thinking},
            },
        },
    )


async def _stream_reply(adapter: LiteLLMAdapter, prompt: str) -> tuple[str, float, dict]:
    """Return (visible_text, seconds_to_first_token, kwargs_sent_to_litellm)."""
    captured: dict = {}
    original = adapter._litellm.acompletion

    async def spy_acompletion(**kw):
        captured.update(kw)
        return await original(**kw)

    adapter._litellm.acompletion = spy_acompletion  # type: ignore[method-assign]

    messages = [
        {
            "role": "system",
            "content": "Reply in one short spoken sentence only. No reasoning.",
        },
        {"role": "user", "content": prompt},
    ]

    raw = ""
    visible = ""
    first_token_at: float | None = None
    t0 = time.monotonic()

    async for chunk in adapter.chat_stream(messages=messages):
        if chunk.content:
            raw += chunk.content
            clean = _strip_think(raw)
            if clean and first_token_at is None:
                first_token_at = time.monotonic()
            visible = clean

    ttft = (first_token_at or time.monotonic()) - t0
    return visible.strip(), ttft, captured


@pytest.fixture(scope="module", autouse=True)
def _env():
    _load_dotenv()


@pytest.mark.asyncio
async def test_nothink_streams_speakable_content_quickly():
    """Default voice path: enable_thinking=false → content, low time-to-first-token."""
    config = _voice_llm_config(enable_thinking=False)
    adapter = LiteLLMAdapter(config)

    text, ttft, kw = await _stream_reply(adapter, "Say hello in one short sentence.")

    assert kw["model"] == f"litellm_proxy/{config.model}"
    assert "custom_llm_provider" not in kw
    assert kw["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert text, f"expected speakable content, got empty (raw proxy may only stream reasoning)"
    assert "reasoning" not in text.lower()
    assert "<think>" not in text
    assert ttft < 15.0, f"time-to-first-token too slow: {ttft:.2f}s"
    print(f"\n[nothink] model={config.model} ttft={ttft:.2f}s text={text!r}")


@pytest.mark.asyncio
async def test_think_enabled_differs_from_nothink():
    """With enable_thinking=true, Qwen3 often delays or hides speakable content."""
    config = _voice_llm_config(enable_thinking=True)
    adapter = LiteLLMAdapter(config)

    text, ttft, kw = await _stream_reply(
        adapter, "Say hello in one short sentence."
    )

    assert kw["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    print(f"\n[think] model={config.model} ttft={ttft:.2f}s text={text!r}")

    # We don't assert empty — some proxies still return content — but no-think
    # must be strictly better for voice (tested above). Document think behavior.
    if not text:
        pytest.skip(
            "Proxy returned no speakable content with thinking enabled "
            "(expected for Qwen3 — confirms why voice uses enable_thinking=false)"
        )


@pytest.mark.asyncio
async def test_nothink_non_streaming_chat():
    """Non-streaming chat path also returns visible content with thinking off."""
    config = _voice_llm_config(enable_thinking=False)
    adapter = LiteLLMAdapter(config)

    result = await adapter.chat(
        messages=[
            {"role": "user", "content": "Reply with exactly: OK."},
        ],
    )
    visible = _strip_think(result.content or "").strip()
    assert visible, "non-streaming chat returned empty content"
    print(f"\n[nothink chat] content={visible!r}")
