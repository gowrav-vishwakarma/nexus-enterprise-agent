"""Mock LID adapter for tests."""

from __future__ import annotations

from typing import Optional

from nexus.realtime.adapters.lid.base import LIDAdapter, LIDResult
from nexus.realtime.config import LIDConfig


class MockLID(LIDAdapter):
    """Deterministic LID that returns configured or decoded language."""

    def __init__(
        self,
        config: Optional[LIDConfig] = None,
        *,
        fixed_language: str | None = None,
        english_text: str | None = None,
    ) -> None:
        super().__init__(config or LIDConfig(provider="mock"))
        self.fixed_language = fixed_language or self.config.extra.get("language")
        self.english_text = english_text or self.config.extra.get("english_text")

    async def detect(
        self, audio: bytes, *, fallback_language: str | None = None
    ) -> LIDResult:
        lang = self.fixed_language or fallback_language or self.config.fallback_language
        if self.fixed_language is None:
            try:
                decoded = audio.decode("utf-8").strip()
                if decoded.startswith("lang:"):
                    lang = decoded.split(":", 1)[1].split()[0]
            except UnicodeDecodeError:
                pass
        en_text = self.english_text if lang == "en" else None
        return LIDResult(language=lang, confidence=1.0, english_text=en_text)
