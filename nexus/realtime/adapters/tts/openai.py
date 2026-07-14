"""OpenAI TTS adapter using the audio/speech REST endpoint via httpx."""

from __future__ import annotations

from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.config import TTSConfig


class OpenAITTS(TTSAdapter):
    """Text-to-speech using OpenAI's speech synthesis API."""

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self._model = config.model or "tts-1"
        self._voice = config.voice or "alloy"
        self._base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
        # OpenAI uses 'response_format'; map common pcm/mp3 names.
        self._format = "mp3" if config.audio_format in ("mp3", "pcm16") else config.audio_format
        if config.audio_format == "pcm16":
            self._format = "pcm"

    async def synthesize(
        self, text: str, *, language: str | None = None, voice: str | None = None
    ) -> bytes:
        """Synthesize text into audio bytes."""
        import httpx

        headers = {
            "Authorization": f"Bearer {self.config.get_api_key()}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "voice": self._voice,
            "input": text,
            "response_format": self._format,
            "speed": self.config.speed,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/audio/speech", headers=headers, json=body
            )
            resp.raise_for_status()
            return resp.content
