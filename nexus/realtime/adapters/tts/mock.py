"""Mock TTS adapter for tests and local development.

It encodes the text as UTF-8 bytes prefixed with a marker, so tests can assert
on the synthesized payload deterministically without audio hardware.
"""

from __future__ import annotations

from typing import Optional

from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.config import TTSConfig


class MockTTS(TTSAdapter):
    """Deterministic TTS that returns ``b"AUDIO:" + text``."""

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        super().__init__(config or TTSConfig(provider="mock"))

    async def synthesize(
        self, text: str, *, language: str | None = None, voice: str | None = None
    ) -> bytes:
        """Return a deterministic byte payload derived from the text."""
        prefix = f"AUDIO:{language or 'default'}:"
        return prefix.encode("utf-8") + text.encode("utf-8")
