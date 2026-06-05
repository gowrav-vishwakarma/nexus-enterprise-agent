"""WebSocket transport.

Works with both FastAPI/Starlette ``WebSocket`` objects and the ``websockets``
library connections by duck-typing the send/receive methods. Binary frames are
treated as audio; text frames are JSON control messages (e.g. DTMF, text input).
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Optional

from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.transport.base import Transport

logger = logging.getLogger(__name__)


class WebSocketTransport(Transport):
    """Adapt a WebSocket connection to the realtime Transport interface.

    Parameters
    ----------
    ws:
        A FastAPI/Starlette ``WebSocket`` (has ``receive``/``send_bytes``/
        ``send_text``) or a ``websockets`` connection (async-iterable, ``send``).
    send_audio_as_base64:
        When True, audio is sent inside JSON events (``audio_out`` with
        ``audio_b64``) instead of as binary frames. Useful for JSON-only clients.
    on_control:
        Optional callback invoked with parsed JSON control messages.
    """

    def __init__(
        self,
        ws: Any,
        *,
        send_audio_as_base64: bool = False,
        on_control: Optional[Any] = None,
    ) -> None:
        self.ws = ws
        self.send_audio_as_base64 = send_audio_as_base64
        self.on_control = on_control
        self._is_fastapi = hasattr(ws, "send_bytes") and hasattr(ws, "receive")

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield binary audio frames; dispatch text frames to ``on_control``."""
        if self._is_fastapi:
            async for chunk in self._receive_fastapi():
                yield chunk
        else:
            async for chunk in self._receive_websockets():
                yield chunk

    async def _receive_fastapi(self) -> AsyncIterator[bytes]:
        from starlette.websockets import WebSocketDisconnect

        while True:
            try:
                message = await self.ws.receive()
            except WebSocketDisconnect:
                return
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                yield message["bytes"]
            elif message.get("text") is not None:
                self._handle_control(message["text"])

    async def _receive_websockets(self) -> AsyncIterator[bytes]:
        try:
            async for message in self.ws:
                if isinstance(message, (bytes, bytearray)):
                    yield bytes(message)
                elif isinstance(message, str):
                    self._handle_control(message)
        except Exception as exc:  # pragma: no cover - connection closed
            logger.debug("WebSocket receive ended: %s", exc)
            return

    def _handle_control(self, text: str) -> None:
        """Parse a JSON control frame and forward to the callback."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        if self.on_control:
            self.on_control(payload)

    async def send_audio(self, chunk: bytes) -> None:
        """Send an audio chunk as a binary frame (or base64 JSON if configured)."""
        if self.send_audio_as_base64:
            import base64

            await self._send_text(
                json.dumps({"type": "audio_out", "audio_b64": base64.b64encode(chunk).decode("ascii")})
            )
            return
        if self._is_fastapi:
            await self.ws.send_bytes(chunk)
        else:
            await self.ws.send(chunk)

    async def send_event(self, event: RealtimeStreamEvent) -> None:
        """Send a structured event as a JSON text frame."""
        payload = event.model_dump(exclude_none=True)
        if event.audio is not None and self.send_audio_as_base64:
            payload["audio_b64"] = event.audio_b64
        await self._send_text(json.dumps(payload))

    async def _send_text(self, text: str) -> None:
        if self._is_fastapi:
            await self.ws.send_text(text)
        else:
            await self.ws.send(text)

    async def close(self) -> None:
        """Close the underlying socket."""
        try:
            await self.ws.close()
        except Exception:  # pragma: no cover
            pass
