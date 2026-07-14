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

from nexus.realtime.adapters.factory import build_lid, build_stt, build_tts, build_vad
from nexus.realtime.adapters.lid.base import LIDAdapter
from nexus.realtime.adapters.stt.base import STTAdapter
from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.adapters.vad.base import VADAdapter, VADEvent
from nexus.realtime.config import RealtimeAgentConfig
from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.languages import (
    DEFAULT_LANGUAGE,
    detect_language_request,
    resolve as resolve_language,
    tts_voice_for,
)
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_SENTENCE_BOUNDARIES = (".", "!", "?", "\n", ";", "।")


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
        lid: Optional[LIDAdapter] = None,
        server_registry: Optional[Any] = None,
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
        _registry = server_registry
        _ctx = self.run_context
        self.stt = stt or build_stt(
            config.effective_stt(), registry=_registry, run_context=_ctx
        )
        self.tts = tts or build_tts(
            config.effective_tts(), registry=_registry, run_context=_ctx
        )
        self.vad = vad or build_vad(
            config.effective_vad(), registry=_registry, run_context=_ctx
        )
        _lid_cfg = config.effective_lid()
        self.lid = lid or (build_lid(_lid_cfg, registry=_registry, run_context=_ctx) if _lid_cfg else None)
        self.session_lang: str | None = None
        self.forced_lang: str | None = None
        self._speak = config.modality == "voice_cascaded"

    def _maybe_register_ivr(self) -> None:
        """Auto-register the IVR plugin when the agent declares it."""
        if "ivr_menu" in self.config.agent.tool_plugins:
            from nexus.realtime.tools.ivr import IVRMenuPlugin

            try:
                self.tool_registry.register_plugin(IVRMenuPlugin())
            except Exception:  # pragma: no cover - already registered
                pass

    def reset_language_state(self) -> None:
        """Clear per-session language detection and sticky override."""
        self.session_lang = None
        self.forced_lang = None

    def _allowed_language_codes(self) -> frozenset[str]:
        return frozenset(
            code.lower().split("-")[0] for code in self.config.effective_languages().allowed
        )

    def _clamp_language(self, code: str | None) -> str:
        langs = self.config.effective_languages()
        allowed = self._allowed_language_codes()
        norm = (code or langs.default or DEFAULT_LANGUAGE).lower().split("-")[0]
        if norm in allowed:
            return norm
        default = (
            langs.default or self.config.effective_stt().language or DEFAULT_LANGUAGE
        ).lower().split("-")[0]
        if default in allowed:
            return default
        return next(iter(allowed))

    def _language_fallback(self) -> str:
        langs = self.config.effective_languages()
        default = langs.default or self.config.effective_stt().language or DEFAULT_LANGUAGE
        return self.forced_lang or self.session_lang or default

    def _apply_reply_language(self, reply_lang: str, detected_lang: str) -> None:
        lang_info = resolve_language(reply_lang)
        self.run_context.metadata["reply_language"] = reply_lang
        self.run_context.metadata["reply_language_name"] = lang_info.name
        self.run_context.metadata["detected_language"] = detected_lang

    def seed_language_metadata(self) -> None:
        """Seed allowed/default language keys before the first user utterance."""
        langs = self.config.effective_languages()
        default = self._clamp_language(langs.default)
        self.run_context.metadata["allowed_languages"] = sorted(self._allowed_language_codes())
        self._apply_reply_language(default, default)
        self.session_lang = default

    def _initial_reply_language(self) -> str:
        ir = self.config.effective_initial_response()
        if ir.reply_language:
            return self._clamp_language(ir.reply_language)
        langs = self.config.effective_languages()
        return self._clamp_language(langs.default)

    async def speak_text(
        self,
        text: str,
        *,
        reply_lang: str | None = None,
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Synthesize fixed text to audio without calling the LLM."""
        stripped = text.strip()
        if not stripped:
            return
        tts_lang = reply_lang
        tts_voice = tts_voice_for(tts_lang, self.config.effective_tts().voice) if tts_lang else None
        kwargs: dict[str, Any] = {}
        if tts_lang:
            kwargs["language"] = tts_lang
        if tts_voice:
            kwargs["voice"] = tts_voice
        audio = await self.tts.synthesize(stripped, **kwargs)
        yield RealtimeStreamEvent.text_delta(stripped)
        yield RealtimeStreamEvent.audio_chunk(
            audio, text=stripped, language=tts_lang, voice=tts_voice
        )
        yield RealtimeStreamEvent(
            event_type="final_response",
            content=stripped,
            data={"final_response": stripped, "session_id": self.run_context.session_id},
        )

    async def run_initial_response(
        self,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Speak connect-time greeting or IVR opening when configured."""
        ir = self.config.effective_initial_response()
        if ir.mode == "none":
            return

        self.seed_language_metadata()
        reply_lang = self._initial_reply_language()
        self._apply_reply_language(reply_lang, reply_lang)

        if ir.mode == "proactive":
            if ir.via_llm:
                trigger = (
                    ir.llm_trigger
                    or "The caller just connected. Greet them briefly in the default language."
                )
                async for ev in self.process_text(
                    trigger,
                    session_id=session_id,
                    emit_transcript=ir.emit_transcript,
                    reply_lang=reply_lang,
                    detected_lang=reply_lang,
                ):
                    yield ev
                return
            if not ir.text:
                return
            async for ev in self.speak_text(ir.text, reply_lang=reply_lang):
                yield ev
            return

        if ir.mode == "ivr":
            if ir.via_llm:
                trigger = (
                    ir.llm_trigger
                    or "The caller just connected. Use play_prompt to present the main menu."
                )
                async for ev in self.process_text(
                    trigger,
                    session_id=session_id,
                    emit_transcript=ir.emit_transcript,
                    reply_lang=reply_lang,
                    detected_lang=reply_lang,
                ):
                    yield ev
                return
            script = list(ir.ivr_script or [])
            if not script and ir.text:
                script = [ir.text]
            for line in script:
                async for ev in self.speak_text(line, reply_lang=reply_lang):
                    yield ev

    async def process_text(
        self,
        text: str,
        session_id: Optional[str] = None,
        *,
        speak: Optional[bool] = None,
        emit_transcript: bool = True,
        reply_lang: str | None = None,
        detected_lang: str | None = None,
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Run the agent on already-transcribed text and stream reply events."""
        if emit_transcript:
            data: dict[str, Any] = {}
            if reply_lang:
                data["language"] = reply_lang
            if detected_lang and detected_lang != reply_lang:
                data["detected_language"] = detected_lang
            yield RealtimeStreamEvent.transcript(text, final=True, **data)
        async for ev in self._agent_stream(text, session_id, speak, reply_lang=reply_lang):
            yield ev

    async def _agent_stream(
        self,
        text: str,
        session_id: Optional[str],
        speak: Optional[bool],
        *,
        reply_lang: str | None = None,
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Run the agent (streaming) and interleave TTS audio with text deltas."""
        do_speak = self._speak if speak is None else speak
        tts_lang = reply_lang
        tts_voice = None
        if self.lid is not None and tts_lang:
            tts_voice = tts_voice_for(tts_lang, self.config.effective_tts().voice)
        sentence_buffer = ""
        final_text: Optional[str] = None
        spoke_audio = False

        async def _synthesize(sentence: str) -> bytes:
            kwargs: dict[str, Any] = {}
            if tts_lang:
                kwargs["language"] = tts_lang
            if tts_voice:
                kwargs["voice"] = tts_voice
            return await self.tts.synthesize(sentence, **kwargs)

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
                            audio = await _synthesize(sentence)
                            spoke_audio = True
                            yield RealtimeStreamEvent.audio_chunk(
                                audio, text=sentence, language=tts_lang, voice=tts_voice
                            )
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
            audio = await _synthesize(sentence_buffer.strip())
            spoke_audio = True
            yield RealtimeStreamEvent.audio_chunk(
                audio,
                text=sentence_buffer.strip(),
                language=tts_lang,
                voice=tts_voice,
            )

        # Some LLM streams only surface text on final_response; still speak it.
        if do_speak and not spoke_audio and final_text and final_text.strip():
            audio = await _synthesize(final_text.strip())
            yield RealtimeStreamEvent.audio_chunk(
                audio,
                text=final_text.strip(),
                language=tts_lang,
                voice=tts_voice,
            )

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
        if self.lid is None:
            transcript = await self.stt.transcribe(
                audio, mime_type=mime_type, language=self.config.effective_stt().language
            )
            if not transcript:
                yield RealtimeStreamEvent(event_type="event", data={"info": "empty_transcript"})
                return
            async for ev in self.process_text(transcript, session_id=session_id):
                yield ev
            return

        fallback = self._language_fallback()
        detected_lang = fallback
        english_text: str | None = None
        allowed = self._allowed_language_codes()
        self.run_context.metadata["allowed_languages"] = sorted(allowed)

        try:
            lid_result = await self.lid.detect(audio, fallback_language=fallback)
            detected_lang = self._clamp_language(lid_result.language)
            english_text = lid_result.english_text
            self.session_lang = detected_lang
        except Exception as exc:
            logger.error("LID failed: %s", exc, exc_info=True)
            detected_lang = self._clamp_language(fallback)
            self.session_lang = detected_lang

        if detected_lang == "en":
            # Indic-Conformer has no English head (joint_post_net_en). English
            # transcription comes from faster-whisper LID only — same as ankpal-voice.
            if english_text:
                transcript = english_text
            else:
                logger.warning(
                    "English detected but LID returned no transcript; skipping Conformer"
                )
                transcript = ""
        else:
            transcript = await self.stt.transcribe(
                audio, mime_type=mime_type, language=detected_lang
            )

        if not transcript:
            yield RealtimeStreamEvent(event_type="event", data={"info": "empty_transcript"})
            return

        requested = detect_language_request(transcript, allowed=allowed)
        if requested is not None:
            requested = self._clamp_language(requested)
            if requested != detected_lang or self.forced_lang != requested:
                logger.info(
                    "Spoken language switch request -> %s (detected=%s)",
                    requested,
                    detected_lang,
                )
            self.forced_lang = requested
            self.session_lang = requested
            reply_lang = requested
        elif self.forced_lang:
            if detected_lang != self.forced_lang:
                logger.info(
                    "Sticking forced_lang=%s (detected=%s)",
                    self.forced_lang,
                    detected_lang,
                )
            reply_lang = self.forced_lang
            self.session_lang = reply_lang
        else:
            reply_lang = detected_lang
            self.session_lang = reply_lang

        self._apply_reply_language(reply_lang, detected_lang)

        async for ev in self.process_text(
            transcript,
            session_id=session_id,
            reply_lang=reply_lang,
            detected_lang=detected_lang,
        ):
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
