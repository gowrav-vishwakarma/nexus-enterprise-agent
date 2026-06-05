"""OpenAI (Whisper / gpt-4o-transcribe) STT adapter.

Uses the OpenAI audio transcription REST endpoint via httpx. The ``openai``
client is not required. Requires an API key in the STT config.
"""

from __future__ import annotations

import io

from nexus.realtime.adapters.stt.base import STTAdapter
from nexus.realtime.config import STTConfig


class OpenAISTT(STTAdapter):
    """Batch transcription using OpenAI's audio API."""

    def __init__(self, config: STTConfig) -> None:
        super().__init__(config)
        self._model = config.model or "whisper-1"
        self._base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")

    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        """Send the audio blob to the transcription endpoint and return text."""
        import httpx

        ext = mime_type.split("/")[-1] if "/" in mime_type else "wav"
        files = {"file": (f"audio.{ext}", io.BytesIO(audio), mime_type)}
        data = {"model": self._model}
        if self.config.language:
            data["language"] = self.config.language
        headers = {"Authorization": f"Bearer {self.config.get_api_key()}"}

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/audio/transcriptions",
                headers=headers,
                data=data,
                files=files,
            )
            resp.raise_for_status()
            payload = resp.json()
        return (payload.get("text") or "").strip()
