"""Deepgram STT adapter (batch + streaming).

Batch transcription uses the Deepgram REST API via httpx. Streaming uses the
Deepgram realtime WebSocket (requires the ``websockets`` package from the
``realtime`` extra).
"""

from __future__ import annotations

from typing import AsyncIterator

from nexus.realtime.adapters.stt.base import STTAdapter, STTResult
from nexus.realtime.config import STTConfig


class DeepgramSTT(STTAdapter):
    """Deepgram Nova transcription."""

    def __init__(self, config: STTConfig) -> None:
        super().__init__(config)
        self._model = config.model or "nova-3"
        self._base_url = (config.base_url or "https://api.deepgram.com/v1").rstrip("/")

    async def transcribe(
        self, audio: bytes, mime_type: str = "audio/wav", *, language: str | None = None
    ) -> str:
        """Batch transcription via Deepgram REST."""
        import httpx

        lang = language or self.config.language
        params = {"model": self._model, "language": lang, "smart_format": "true"}
        headers = {
            "Authorization": f"Token {self.config.get_api_key()}",
            "Content-Type": mime_type,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/listen",
                headers=headers,
                params=params,
                content=audio,
            )
            resp.raise_for_status()
            payload = resp.json()
        try:
            return (
                payload["results"]["channels"][0]["alternatives"][0]["transcript"]
            ).strip()
        except (KeyError, IndexError):
            return ""

    async def stream_transcribe(
        self, audio_stream: AsyncIterator[bytes], *, language: str | None = None
    ) -> AsyncIterator[STTResult]:
        """Streaming transcription via Deepgram realtime WebSocket."""
        try:
            import json

            import websockets
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "Deepgram streaming requires 'websockets'. Install with "
                "pip install nexus-enterprise-agent[realtime]"
            ) from exc

        ws_base = self._base_url.replace("https://", "wss://").replace("http://", "ws://")
        sample_rate = self.config.sample_rate
        lang = language or self.config.language
        url = (
            f"{ws_base}/listen?model={self._model}&language={lang}"
            f"&encoding=linear16&sample_rate={sample_rate}&interim_results="
            f"{'true' if self.config.interim_results else 'false'}"
        )
        headers = {"Authorization": f"Token {self.config.get_api_key()}"}

        async with websockets.connect(url, additional_headers=headers) as ws:
            async def _send() -> None:
                async for chunk in audio_stream:
                    await ws.send(chunk)
                await ws.send(json.dumps({"type": "CloseStream"}))

            import asyncio

            send_task = asyncio.create_task(_send())
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    alt = (
                        msg.get("channel", {})
                        .get("alternatives", [{}])[0]
                    )
                    text = (alt.get("transcript") or "").strip()
                    if not text:
                        continue
                    yield STTResult(
                        text=text,
                        is_final=bool(msg.get("is_final")),
                        confidence=float(alt.get("confidence", 1.0)),
                    )
            finally:
                send_task.cancel()
