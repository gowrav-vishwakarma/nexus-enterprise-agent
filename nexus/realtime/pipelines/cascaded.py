"""Cascaded voice pipeline: VAD -> STT -> AgentRunner -> TTS.

This wraps the unchanged :class:`~nexus.runner.agent_runner.AgentRunner`. Audio
in is segmented by VAD, transcribed by STT, fed to the agent as text, and the
agent's streamed text reply is synthesized to audio sentence-by-sentence so
playback starts before the full reply is ready.

- ``process_text`` -- input already transcribed (channels, S2S fallback).
- ``process_utterance`` -- a single complete audio blob (half-duplex / IVR).
- ``process_audio_stream`` -- a continuous audio stream (segmented by VAD).
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from nexus.realtime.adapters.factory import build_stt, build_tts, build_vad
from nexus.realtime.adapters.stt.base import STTAdapter
from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.adapters.vad.base import VADAdapter, VADEvent
from nexus.realtime.config import RealtimeAgentConfig
from nexus.realtime.events import RealtimeStreamEvent
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_SENTENCE_BOUNDARIES = (".", "!", "?", "\n", ";")


def _first_boundary(text: str) -> int:
    """Index of the earliest sentence boundary in text, or -1."""
    found = [text.find(b) for b in _SENTENCE_BOUNDARIES if b in text]
    return min(found) if found else -1


class CascadedVoicePipeline:
    """Drive a voice agent using separate STT, LLM, and TTS stages."""

    def __init__(
        self,
        config: RealtimeAgentConfig,
        tool_registry: Optional[ToolRegistry] = None,
        storage_config: Optional[Any] = None,
        run_context: Optional[RunContext] = None,
        cross_session_memory_store: Optional[Any] = None,
        event_emitter: Optional[Any] = None,
        *,
        stt: Optional[STTAdapter] = None,
        tts: Optional[TTSAdapter] = None,
        vad: Optional[VADAdapter] = None,
    ) -> None:
        self.config = config
        self.duplex = config.duplex
        self.tool_registry = tool_registry or ToolRegistry()
        self._maybe_register_ivr()

        self.runner = AgentRunner(
            config=config.agent,
            tool_registry=self.tool_registry,
            storage_config=storage_config,
            run_context=run_context,
            event_emitter=event_emitter,
            cross_session_memory_store=cross_session_memory_store,
        )
        self.run_context = self.runner.run_context
        self.stt = stt or build_stt(config.effective_stt())
        self.tts = tts or build_tts(config.effective_tts())
        self.vad = vad or build_vad(config.effective_vad())
        self._speak = config.modality == "voice_cascaded"

    def _maybe_register_ivr(self) -> None:
        """Auto-register the IVR plugin when the agent declares it."""
        if "ivr_menu" in self.config.agent.tool_plugins:
            from nexus.realtime.tools.ivr import IVRMenuPlugin

            try:
                self.tool_registry.register_plugin(IVRMenuPlugin())
            except Exception:  # pragma: no cover - already registered
                pass

    async def process_text(
        self,
        text: str,
        session_id: Optional[str] = None,
        *,
        speak: Optional[bool] = None,
        emit_transcript: bool = True,
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Run the agent on already-transcribed text and stream reply events."""
        if emit_transcript:
            yield RealtimeStreamEvent.transcript(text, final=True)
        async for ev in self._agent_stream(text, session_id, speak):
            yield ev

    async def _agent_stream(
        self, text: str, session_id: Optional[str], speak: Optional[bool]
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Run the agent (streaming) and interleave TTS audio with text deltas."""
        do_speak = self._speak if speak is None else speak
        sentence_buffer = ""
        final_text: Optional[str] = None

        async for ev in self.runner.run_stream(text, session_id=session_id, stream=True):
            if ev.event_type == "content" and ev.content:
                yield RealtimeStreamEvent.text_delta(ev.content)
                if do_speak:
                    sentence_buffer += ev.content
                    while True:
                        idx = _first_boundary(sentence_buffer)
                        if idx < 0:
                            break
                        sentence = sentence_buffer[: idx + 1].strip()
                        sentence_buffer = sentence_buffer[idx + 1 :]
                        if sentence:
                            audio = await self.tts.synthesize(sentence)
                            yield RealtimeStreamEvent.audio_chunk(audio, text=sentence)
            elif ev.event_type == "tool_call":
                yield RealtimeStreamEvent(event_type="tool_call", data=ev.data)
            elif ev.event_type == "tool_result":
                yield RealtimeStreamEvent(event_type="tool_result", content=ev.content, data=ev.data)
            elif ev.event_type == "error":
                yield RealtimeStreamEvent(event_type="error", content=ev.content, data=ev.data)
            elif ev.event_type == "final_response":
                final_text = ev.content

        # Flush any trailing partial sentence.
        if do_speak and sentence_buffer.strip():
            audio = await self.tts.synthesize(sentence_buffer.strip())
            yield RealtimeStreamEvent.audio_chunk(audio, text=sentence_buffer.strip())

        terminal = bool(self.run_context.metadata.get("ivr_terminal"))
        yield RealtimeStreamEvent(
            event_type="final_response",
            content=final_text,
            data={
                "final_response": final_text,
                "session_id": self.run_context.session_id,
                "ivr_actions": self.run_context.metadata.get("ivr_actions"),
                "terminal": terminal,
            },
        )

    async def process_utterance(
        self,
        audio: bytes,
        session_id: Optional[str] = None,
        *,
        mime_type: str = "audio/wav",
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Transcribe one audio blob and stream the agent reply."""
        transcript = await self.stt.transcribe(audio, mime_type=mime_type)
        if not transcript:
            yield RealtimeStreamEvent(event_type="event", data={"info": "empty_transcript"})
            return
        async for ev in self.process_text(transcript, session_id=session_id):
            yield ev

    async def process_audio_stream(
        self,
        audio_in: AsyncIterator[bytes],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Segment a continuous audio stream by VAD and respond per utterance.

        Half-duplex: strict turn-taking (used for IVR/telephony). Full-duplex:
        the user can interrupt the agent (barge-in) -- a new SPEECH_START while
        the agent is speaking cancels the in-flight response.
        """
        if self.duplex == "full":
            async for ev in self._full_duplex(audio_in, session_id):
                yield ev
            return

        self.vad.reset()
        yield RealtimeStreamEvent(event_type="session_started", data={"duplex": self.duplex})

        async for frame in audio_in:
            event = self.vad.process_frame(frame)
            if event == VADEvent.SPEECH_START:
                yield RealtimeStreamEvent(event_type="event", data={"vad": "speech_start"})
            elif event == VADEvent.SPEECH_END:
                utterance = self.vad.take_utterance()
                async for ev in self.process_utterance(utterance, session_id=session_id):
                    yield ev
                if self.run_context.metadata.get("ivr_terminal"):
                    yield RealtimeStreamEvent(event_type="turn_end", data={"terminal": True})
                    return

    async def _full_duplex(
        self,
        audio_in: AsyncIterator[bytes],
        session_id: Optional[str],
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Concurrent listen+speak loop with barge-in cancellation."""
        import asyncio

        self.vad.reset()
        out_q: asyncio.Queue = asyncio.Queue()
        state: dict[str, Any] = {"response_task": None, "input_done": False}
        DONE = object()
        RESP_DONE = object()

        async def run_response(utterance: bytes) -> None:
            try:
                async for ev in self.process_utterance(utterance, session_id=session_id):
                    await out_q.put(ev)
            except asyncio.CancelledError:
                raise
            finally:
                await out_q.put(RESP_DONE)

        async def reader() -> None:
            async for frame in audio_in:
                ev = self.vad.process_frame(frame)
                if ev == VADEvent.SPEECH_START:
                    await out_q.put(
                        RealtimeStreamEvent(event_type="event", data={"vad": "speech_start"})
                    )
                    rt = state["response_task"]
                    if rt is not None and not rt.done():
                        await out_q.put(
                            RealtimeStreamEvent(
                                event_type="barge_in", data={"info": "user interrupted"}
                            )
                        )
                        rt.cancel()
                elif ev == VADEvent.SPEECH_END:
                    utterance = self.vad.take_utterance()
                    state["response_task"] = asyncio.create_task(run_response(utterance))
            await out_q.put(DONE)

        reader_task = asyncio.create_task(reader())
        yield RealtimeStreamEvent(event_type="session_started", data={"duplex": "full"})

        try:
            while True:
                item = await out_q.get()
                if item is DONE:
                    state["input_done"] = True
                    rt = state["response_task"]
                    if rt is None or rt.done():
                        break
                elif item is RESP_DONE:
                    rt = state["response_task"]
                    if state["input_done"] and (rt is None or rt.done()):
                        break
                else:
                    yield item
        finally:
            reader_task.cancel()
            rt = state["response_task"]
            if rt is not None and not rt.done():
                rt.cancel()
