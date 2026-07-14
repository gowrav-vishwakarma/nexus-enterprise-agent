"""Base text-to-speech adapter interface."""

from __future__ import annotations

import abc
from typing import AsyncIterator

from nexus.realtime.config import TTSConfig


class TTSAdapter(abc.ABC):
    """Synthesize text into audio bytes.

    Implementations provide a batch ``synthesize`` and a streaming
    ``stream_synthesize`` that turns a stream of text deltas into a stream of
    audio chunks. The streaming default synthesizes sentence-by-sentence so
    audio can start before the full reply is generated.
    """

    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def synthesize(
        self, text: str, *, language: str | None = None, voice: str | None = None
    ) -> bytes:
        """Synthesize a complete text string into audio bytes."""

    async def stream_synthesize(
        self,
        text_stream: AsyncIterator[str],
        *,
        language: str | None = None,
        voice: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Synthesize streamed text, flushing audio per sentence boundary."""
        buffer = ""
        boundaries = (".", "!", "?", "\n")
        async for delta in text_stream:
            if not delta:
                continue
            buffer += delta
            # Flush complete sentences for low-latency playback.
            while any(b in buffer for b in boundaries):
                idx = min(
                    (buffer.find(b) for b in boundaries if b in buffer),
                    default=-1,
                )
                if idx < 0:
                    break
                sentence = buffer[: idx + 1].strip()
                buffer = buffer[idx + 1 :]
                if sentence:
                    yield await self.synthesize(sentence, language=language, voice=voice)
        tail = buffer.strip()
        if tail:
            yield await self.synthesize(tail, language=language, voice=voice)
