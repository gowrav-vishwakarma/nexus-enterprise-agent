import asyncio
import time
from types import SimpleNamespace

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.realtime.adapters.tts.mock import MockTTS
from nexus.realtime.config import RealtimeAgentConfig
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.session.manager import SessionManager


def _pipeline(tts) -> CascadedVoicePipeline:
    cfg = RealtimeAgentConfig(
        name="va",
        agent=AgentConfig(
            name="va", llm=LLMProviderConfig(provider="openai", model="x", api_key="sk")
        ),
    )
    p = CascadedVoicePipeline(cfg, storage_config=SessionManager(), tts=MockTTS())
    p.tts.synthesize = tts
    return p


def _content(text):
    return SimpleNamespace(event_type="content", content=text, data=None)


def _final(text):
    return SimpleNamespace(event_type="final_response", content=text, data=None)


@pytest.mark.asyncio
async def test_llm_stream_keeps_reading_while_tts_runs():
    async def slow_tts(text, **kw):
        await asyncio.sleep(0.5)
        return text.encode()

    p = _pipeline(slow_tts)
    t0 = time.monotonic()
    pulled: list[float] = []

    async def fake_llm(text, session_id=None, stream=True):
        for tok in ["One.", " Two.", " Three."]:
            pulled.append(time.monotonic() - t0)
            await asyncio.sleep(0.05)
            yield _content(tok)
        yield _final("One. Two. Three.")

    p.runner.run_stream = fake_llm
    events = [ev async for ev in p._agent_stream("hi", None, True)]

    assert pulled[-1] < 0.5  # all LLM tokens read before the first 0.5s TTS call finished
    audio = [e for e in events if e.event_type == "audio_out"]
    assert [e.audio for e in audio] == [b"One.", b"Two.", b"Three."]  # every sentence, in order
    assert events[-1].event_type == "final_response"


@pytest.mark.asyncio
async def test_audio_is_sent_while_a_tool_runs():
    async def fast_tts(text, **kw):
        await asyncio.sleep(0.05)
        return text.encode()

    p = _pipeline(fast_tts)

    async def fake_llm(text, session_id=None, stream=True):
        yield _content("Let me check your balance.")
        yield SimpleNamespace(event_type="tool_call", content=None, data={"name": "balance"})
        await asyncio.sleep(1.0)  # the tool runs; no LLM events meanwhile
        yield _content(" You have 5 rupees.")
        yield _final("Let me check your balance. You have 5 rupees.")

    p.runner.run_stream = fake_llm
    t0 = time.monotonic()
    first_audio_at = None
    async for ev in p._agent_stream("hi", None, True):
        if ev.event_type == "audio_out" and first_audio_at is None:
            first_audio_at = time.monotonic() - t0
    assert first_audio_at is not None and first_audio_at < 0.5  # not held back by the tool


@pytest.mark.asyncio
async def test_closing_stream_cancels_inflight_tts():
    started = asyncio.Event()
    finished: list[str] = []

    async def slow_tts(text, **kw):
        started.set()
        await asyncio.sleep(1.0)
        finished.append(text)
        return text.encode()

    p = _pipeline(slow_tts)

    async def fake_llm(text, session_id=None, stream=True):
        yield _content("One. Two.")
        yield _final("One. Two.")

    p.runner.run_stream = fake_llm
    stream = p._agent_stream("hi", None, True)
    await stream.__anext__()  # first text delta
    await asyncio.wait_for(started.wait(), 1.0)  # TTS is now synthesizing "One."
    await stream.aclose()  # what barge-in does to the response
    await asyncio.sleep(1.2)
    assert finished == []  # the in-flight call was cancelled, and "Two." never started


@pytest.mark.asyncio
async def test_streamed_tts_chunks_are_sent_as_they_arrive():
    p = _pipeline(None)
    t0 = time.monotonic()

    async def chunked_stream(text_stream, **kw):
        sentence = "".join([t async for t in text_stream])
        for i in range(3):
            await asyncio.sleep(0.2)
            yield f"{sentence}#{i}".encode()

    p.tts.stream_synthesize = chunked_stream

    async def fake_llm(text, session_id=None, stream=True):
        yield _content("Hello there.")
        yield _final("Hello there.")

    p.runner.run_stream = fake_llm
    audio = []
    async for ev in p._agent_stream("hi", None, True):
        if ev.event_type == "audio_out":
            audio.append((ev.audio, time.monotonic() - t0))
    assert [a for a, _ in audio] == [b"Hello there.#0", b"Hello there.#1", b"Hello there.#2"]
    assert audio[0][1] < 0.4  # first chunk sent before the whole sentence is synthesized


@pytest.mark.asyncio
async def test_tts_error_still_raised():
    async def broken_tts(text, **kw):
        raise RuntimeError("tts down")

    p = _pipeline(broken_tts)

    async def fake_llm(text, session_id=None, stream=True):
        yield _content("One. Two.")
        yield _final("One. Two.")

    p.runner.run_stream = fake_llm
    with pytest.raises(RuntimeError, match="tts down"):
        async for _ in p._agent_stream("hi", None, True):
            pass
