"""SIP / telephony media bridge transport (Twilio Media Streams shape).

Most carriers and CPaaS providers (Twilio, Telnyx, Plivo) stream call audio over
a WebSocket as base64 mu-law (G.711) at 8 kHz. This transport decodes inbound
mu-law to PCM16 for the pipeline and encodes synthesized PCM16 back to mu-law.

DTMF key presses arrive as ``dtmf`` events and are forwarded to ``on_dtmf`` (wire
this to ``RunContext.metadata['dtmf_buffer']`` so the ``ivr_menu`` tools can read
them).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, AsyncIterator, Callable, Optional

from nexus.realtime.audio.mulaw import downsample_pcm16, pcm16_to_ulaw, ulaw_to_pcm16
from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.transport.base import Transport

logger = logging.getLogger(__name__)


class TwilioMediaStreamTransport(Transport):
    """Bridge a Twilio-style media WebSocket to the realtime pipeline."""

    def __init__(
        self,
        ws: Any,
        *,
        on_dtmf: Optional[Callable[[str], None]] = None,
        tts_sample_rate: int = 8000,
    ) -> None:
        self.ws = ws
        self.on_dtmf = on_dtmf
        self.tts_sample_rate = tts_sample_rate
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        self._is_fastapi = hasattr(ws, "send_text") and hasattr(ws, "receive")

    async def _recv(self) -> Optional[str]:
        """Receive one text frame (provider control/media JSON)."""
        if self._is_fastapi:
            from starlette.websockets import WebSocketDisconnect

            try:
                message = await self.ws.receive()
            except WebSocketDisconnect:
                return None
            if message.get("type") == "websocket.disconnect":
                return None
            return message.get("text")
        try:
            return await self.ws.recv()
        except Exception:  # pragma: no cover - connection closed
            return None

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield PCM16 (8 kHz) frames decoded from inbound mu-law media."""
        while True:
            raw = await self._recv()
            if raw is None:
                return
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            event = msg.get("event")
            if event == "start":
                start = msg.get("start", {})
                self.stream_sid = msg.get("streamSid") or start.get("streamSid")
                self.call_sid = start.get("callSid")
            elif event == "media":
                payload = msg.get("media", {}).get("payload")
                if payload:
                    yield ulaw_to_pcm16(base64.b64decode(payload))
            elif event == "dtmf":
                digit = msg.get("dtmf", {}).get("digit")
                if digit and self.on_dtmf:
                    self.on_dtmf(str(digit))
            elif event == "stop":
                return

    async def send_audio(self, chunk: bytes) -> None:
        """Encode PCM16 to mu-law and send it back on the media stream."""
        if not self.stream_sid:
            logger.debug("TwilioMediaStreamTransport: no streamSid yet; dropping audio")
            return
        pcm = downsample_pcm16(chunk, self.tts_sample_rate, 8000)
        payload = base64.b64encode(pcm16_to_ulaw(pcm)).decode("ascii")
        frame = {
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {"payload": payload},
        }
        await self._send_text(json.dumps(frame))

    async def send_event(self, event: RealtimeStreamEvent) -> None:
        """Send a Twilio ``mark`` for turn boundaries; ignore the rest.

        Twilio's media WS only accepts media/mark/clear frames, so structured
        events are not forwarded; observability goes through the event emitter.
        """
        if not self.stream_sid:
            return
        if event.event_type in ("final_response", "turn_end"):
            await self._send_text(
                json.dumps(
                    {"event": "mark", "streamSid": self.stream_sid, "mark": {"name": event.event_type}}
                )
            )
        elif event.event_type == "barge_in":
            # Clear any buffered outbound audio so the agent stops talking.
            await self._send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

    async def _send_text(self, text: str) -> None:
        if self._is_fastapi:
            await self.ws.send_text(text)
        else:
            await self.ws.send(text)
