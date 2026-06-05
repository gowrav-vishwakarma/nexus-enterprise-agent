"""Mock STT adapter for tests and local development.

It treats incoming audio bytes as UTF-8 text when possible (so tests can feed
"audio" as text), or returns a configured fixed transcript.
"""

from __future__ import annotations

from typing import Optional

from nexus.realtime.adapters.stt.base import STTAdapter
from nexus.realtime.config import STTConfig


class MockSTT(STTAdapter):
    """Deterministic STT that decodes bytes as text or returns a fixed string."""

    def __init__(self, config: Optional[STTConfig] = None, fixed_transcript: Optional[str] = None) -> None:
        super().__init__(config or STTConfig(provider="mock"))
        self.fixed_transcript = fixed_transcript or self.config.extra.get("transcript")

    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        """Return the fixed transcript, else decode bytes as UTF-8 text."""
        if self.fixed_transcript is not None:
            return self.fixed_transcript
        try:
            return audio.decode("utf-8").strip()
        except UnicodeDecodeError:
            return f"[{len(audio)} bytes of audio]"
