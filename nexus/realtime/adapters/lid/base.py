"""Base language-identification adapter interface."""

from __future__ import annotations

import abc

from pydantic import BaseModel, Field

from nexus.realtime.config import LIDConfig


class LIDResult(BaseModel):
    """Language identification result for one utterance."""

    language: str = Field(..., description="Detected ISO language code")
    confidence: float = Field(default=1.0, description="Detection confidence 0..1")
    english_text: str | None = Field(
        default=None,
        description="Whisper English transcript when language is English",
    )


class LIDAdapter(abc.ABC):
    """Detect spoken language from audio before STT."""

    def __init__(self, config: LIDConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def detect(
        self, audio: bytes, *, fallback_language: str | None = None
    ) -> LIDResult:
        """Identify language from a complete audio utterance."""
