"""VoiceTeam: a multi-agent voice conversation pattern.

Implements the "group of agents" idea: a **responder** listens and replies (via a
cascaded or speech-to-speech pipeline), an optional **context_agent** supplies
related information (RAG, lookups, policy) for each turn, and an optional
**listener** can provide a dedicated transcription path. The context agent's
output is injected into the responder's turn so the spoken reply is grounded.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from nexus.realtime.adapters.factory import build_stt, build_vad
from nexus.realtime.adapters.vad.base import VADEvent
from nexus.realtime.config import RealtimeAgentConfig, STTConfig, VADConfig, VoiceTeamConfig
from nexus.realtime.events import RealtimeStreamEvent
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class VoiceTeam:
    """Orchestrate a responder + context agent (+ optional listener) by voice."""

    def __init__(
        self,
        config: VoiceTeamConfig,
        tool_registry: Optional[ToolRegistry] = None,
        storage_config: Optional[Any] = None,
        run_context: Optional[RunContext] = None,
        cross_session_memory_store: Optional[Any] = None,
        event_emitter: Optional[Any] = None,
    ) -> None:
        self.config = config
        self.duplex = config.duplex
        self.run_context = run_context or RunContext()
        self.tool_registry = tool_registry or ToolRegistry()

        self.responder = self._build_pipeline(
            config.responder,
            storage_config,
            cross_session_memory_store,
            event_emitter,
        )

        self.context_runner: Optional[AgentRunner] = None
        if config.context_agent is not None:
            self.context_runner = AgentRunner(
                config=config.context_agent,
                tool_registry=self.tool_registry,
                storage_config=storage_config,
                run_context=self.run_context,
                event_emitter=event_emitter,
                cross_session_memory_store=cross_session_memory_store,
            )

        self._stt, self._vad = self._resolve_listening(config.listener, storage_config)

    def _build_pipeline(
        self,
        rt_config: RealtimeAgentConfig,
        storage_config,
        cross_session_memory_store,
        event_emitter,
    ):
        """Build the responder pipeline (cascaded or speech-to-speech)."""
        common = dict(
            tool_registry=self.tool_registry,
            storage_config=storage_config,
            run_context=self.run_context,
            cross_session_memory_store=cross_session_memory_store,
            event_emitter=event_emitter,
        )
        if rt_config.modality == "voice_s2s":
            from nexus.realtime.pipelines.speech_to_speech import SpeechToSpeechPipeline

            return SpeechToSpeechPipeline(rt_config, **common)
        from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline

        return CascadedVoicePipeline(rt_config, **common)

    def _resolve_listening(self, listener: Optional[RealtimeAgentConfig], storage_config):
        """Pick the STT + VAD used to segment/transcribe inbound audio."""
        # Prefer the responder's own STT/VAD when it is cascaded.
        if hasattr(self.responder, "stt") and hasattr(self.responder, "vad"):
            return self.responder.stt, self.responder.vad
        if listener is not None:
            return build_stt(listener.effective_stt()), build_vad(listener.effective_vad())
        return build_stt(STTConfig(provider="mock")), build_vad(VADConfig(provider="energy"))

    async def _gather_context(self, transcript: str) -> Optional[str]:
        """Ask the context agent for information relevant to this turn."""
        if self.context_runner is None:
            return None
        result = await self.context_runner.run(transcript, stream=False)
        return result.final_response

    def _enrich(self, transcript: str, context: Optional[str]) -> str:
        """Inject the context agent's output into the responder's prompt."""
        if not context:
            return transcript
        var = self.config.context_injection_var
        return f"[{var}]\n{context}\n[/{var}]\n\nUser said: {transcript}"

    async def process_text(
        self, text: str, session_id: Optional[str] = None
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Run one team turn from already-transcribed text."""
        yield RealtimeStreamEvent.transcript(text, final=True)

        context = await self._gather_context(text)
        if context:
            yield RealtimeStreamEvent(
                event_type="event", data={"context_agent": context}
            )

        enriched = self._enrich(text, context)
        async for ev in self.responder.process_text(
            enriched, session_id=session_id, emit_transcript=False
        ):
            yield ev

    async def process_utterance(
        self, audio: bytes, session_id: Optional[str] = None, *, mime_type: str = "audio/wav"
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Transcribe one audio blob and run a team turn."""
        transcript = await self._stt.transcribe(audio, mime_type=mime_type)
        if not transcript:
            yield RealtimeStreamEvent(event_type="event", data={"info": "empty_transcript"})
            return
        async for ev in self.process_text(transcript, session_id=session_id):
            yield ev

    async def process_audio_stream(
        self, audio_in: AsyncIterator[bytes], session_id: Optional[str] = None
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Segment a continuous audio stream and run a team turn per utterance."""
        self._vad.reset()
        yield RealtimeStreamEvent(
            event_type="session_started", data={"pattern": "voice_team", "duplex": self.duplex}
        )
        async for frame in audio_in:
            event = self._vad.process_frame(frame)
            if event == VADEvent.SPEECH_START:
                yield RealtimeStreamEvent(event_type="event", data={"vad": "speech_start"})
            elif event == VADEvent.SPEECH_END:
                utterance = self._vad.take_utterance()
                async for ev in self.process_utterance(utterance, session_id=session_id):
                    yield ev
