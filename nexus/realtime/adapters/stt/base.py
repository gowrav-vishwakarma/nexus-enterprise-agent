"""Base speech-to-text adapter interface."""

from __future__ import annotations

import abc
from typing import AsyncIterator

from pydantic import BaseModel, Field

from nexus.realtime.config import STTConfig


class STTResult(BaseModel):
    """A transcription result (partial or final)."""

    text: str = Field(..., description="Transcribed text")
    is_final: bool = Field(default=True, description="True for a finalized segment")
    confidence: float = Field(default=1.0, description="Provider confidence 0..1")


class STTAdapter(abc.ABC):
    """Transcribe audio to text.

    Implementations provide a batch ``transcribe`` (used for voice notes and
    half-duplex utterances) and a streaming ``stream_transcribe`` (used for
    full-duplex realtime). The streaming default falls back to batch.
    """

    def __init__(self, config: STTConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        """Transcribe a complete audio blob into text."""

    async def stream_transcribe(
        self, audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[STTResult]:
        """Transcribe a stream of audio chunks.

        Default implementation buffers the whole stream then emits one final
        result. Streaming providers should override to emit interim results.
        """
        chunks: list[bytes] = []
        async for chunk in audio_stream:
            chunks.append(chunk)
        text = await self.transcribe(b"".join(chunks))
        if text:
            yield STTResult(text=text, is_final=True)
