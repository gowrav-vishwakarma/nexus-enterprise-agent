"""Route an inbound channel message through an agent and reply.

The router is the glue between channels and the unchanged agent core:

    raw payload -> parse_inbound -> resolve identity -> (transcribe audio)
                -> run executor -> (synthesize audio) -> send_reply

It is transport-agnostic: the caller supplies an ``executor_factory`` that, given
a :class:`RunContext`, returns something with an async ``run(text, session_id=...)``
method (an ``AgentRunner``, ``AgentOrchestrator``, or ``OrchestrationRuntime``).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Protocol

from nexus.channels.base import (
    AgentOutput,
    ChannelAdapter,
    ChannelIdentityResolver,
    InboundMessage,
    StaticIdentityResolver,
)
from nexus.tools.context import RunContext

logger = logging.getLogger(__name__)


class _Executor(Protocol):
    async def run(self, user_message: str, *, session_id: Optional[str] = None) -> Any:
        ...


ExecutorFactory = Callable[[RunContext], _Executor]


class _STTLike(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str = ...) -> str:
        ...


class _TTSLike(Protocol):
    async def synthesize(self, text: str) -> bytes:
        ...


class ChannelRouter:
    """Drive a single inbound message end-to-end for a messaging channel."""

    def __init__(
        self,
        adapter: ChannelAdapter,
        executor_factory: ExecutorFactory,
        *,
        identity_resolver: Optional[ChannelIdentityResolver] = None,
        stt: Optional[_STTLike] = None,
        tts: Optional[_TTSLike] = None,
        reply_with_audio: bool = False,
        vision_executor_factory: Optional[ExecutorFactory] = None,
    ) -> None:
        self.adapter = adapter
        self.executor_factory = executor_factory
        self.identity_resolver: ChannelIdentityResolver = (
            identity_resolver or StaticIdentityResolver()
        )
        self.stt = stt
        self.tts = tts
        self.reply_with_audio = reply_with_audio
        # Optional vision-capable executor (e.g. VisionAgentRunner) for image
        # attachments; falls back to the text executor when not provided.
        self.vision_executor_factory = vision_executor_factory

    async def handle(self, raw: Any) -> AgentOutput:
        """Process one provider payload and deliver the reply."""
        message = await self.adapter.parse_inbound(raw)
        run_context = self.identity_resolver.resolve(message)

        if message.user_input.has_images() and self.vision_executor_factory:
            # Pass the full multimodal input so images reach the vision builder.
            executor = self.vision_executor_factory(run_context)
            result = await executor.run(
                message.user_input, session_id=run_context.session_id
            )
        else:
            text = await self._resolve_text(message)
            executor = self.executor_factory(run_context)
            result = await executor.run(text, session_id=run_context.session_id)
        reply_text = _extract_final_response(result)

        output = AgentOutput(
            text=reply_text,
            session_id=run_context.session_id,
        )

        if self.reply_with_audio and self.tts and reply_text:
            try:
                output.audio = await self.tts.synthesize(reply_text)
            except Exception as exc:  # pragma: no cover - provider failure
                logger.warning("ChannelRouter: TTS synthesis failed: %s", exc)

        await self.adapter.send_reply(message, output)
        return output

    async def _resolve_text(self, message: InboundMessage) -> str:
        """Turn the inbound multimodal input into a text prompt for the agent."""
        text = message.user_input.to_text()
        if not message.user_input.has_audio() or not self.stt:
            return text

        transcripts: list[str] = []
        for audio_part in message.user_input.audio_parts():
            try:
                transcript = await self.stt.transcribe(
                    audio_part.to_bytes(), mime_type=audio_part.mime_type
                )
                if transcript:
                    transcripts.append(transcript)
            except Exception as exc:  # pragma: no cover - provider failure
                logger.warning("ChannelRouter: STT transcription failed: %s", exc)

        combined = " ".join([t for t in [text, *transcripts] if t]).strip()
        return combined


def _extract_final_response(result: Any) -> Optional[str]:
    """Pull a text reply out of an AgentRunResult / AgentGroupResult."""
    return getattr(result, "final_response", None)
