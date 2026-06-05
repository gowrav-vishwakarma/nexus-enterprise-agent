"""WebRTC transport via LiveKit (optional).

LiveKit handles the browser <-> server media plumbing (ICE, SRTP, jitter buffer).
This adapter bridges a LiveKit room's audio track to the realtime pipeline. It
imports ``livekit`` lazily, so the rest of the framework never requires it.

For deployments that prefer not to run LiveKit, use ``WebSocketTransport`` with
a browser client that captures mic audio and streams PCM frames over WebSocket.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.transport.base import Transport

logger = logging.getLogger(__name__)


class LiveKitTransport(Transport):
    """Bridge a LiveKit room audio track to the pipeline.

    Parameters
    ----------
    room:
        A connected ``livekit.rtc.Room``.
    audio_source:
        A ``livekit.rtc.AudioSource`` used to publish synthesized audio back.
    sample_rate / num_channels:
        Output audio format for synthesized frames.
    """

    def __init__(
        self,
        room: Any,
        audio_source: Any,
        *,
        sample_rate: int = 24000,
        num_channels: int = 1,
    ) -> None:
        self.room = room
        self.audio_source = audio_source
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self._data_topic = "nexus-events"

    @classmethod
    async def connect(
        cls,
        url: str,
        token: str,
        *,
        sample_rate: int = 24000,
        num_channels: int = 1,
    ) -> "LiveKitTransport":
        """Connect to a LiveKit room and publish an audio source track."""
        try:
            from livekit import rtc
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "WebRTC transport requires 'livekit'. Install with "
                "pip install livekit livekit-agents (or the realtime extra)."
            ) from exc

        room = rtc.Room()
        await room.connect(url, token)
        source = rtc.AudioSource(sample_rate, num_channels)
        track = rtc.LocalAudioTrack.create_audio_track("nexus-voice", source)
        await room.local_participant.publish_track(track)
        return cls(room, source, sample_rate=sample_rate, num_channels=num_channels)

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield PCM16 frames from the first remote audio track in the room."""
        try:
            from livekit import rtc
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError("livekit is required for LiveKitTransport") from exc

        audio_stream: Optional[Any] = None
        for participant in self.room.remote_participants.values():
            for pub in participant.track_publications.values():
                if pub.track and pub.kind == rtc.TrackKind.KIND_AUDIO:
                    audio_stream = rtc.AudioStream(pub.track)
                    break
            if audio_stream:
                break

        if audio_stream is None:
            logger.warning("LiveKitTransport: no remote audio track found")
            return

        async for frame_event in audio_stream:
            yield bytes(frame_event.frame.data)

    async def send_audio(self, chunk: bytes) -> None:
        """Publish a synthesized PCM16 audio chunk back to the room."""
        try:
            from livekit import rtc
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError("livekit is required for LiveKitTransport") from exc

        frame = rtc.AudioFrame(
            data=chunk,
            sample_rate=self.sample_rate,
            num_channels=self.num_channels,
            samples_per_channel=len(chunk) // (2 * self.num_channels),
        )
        await self.audio_source.capture_frame(frame)

    async def send_event(self, event: RealtimeStreamEvent) -> None:
        """Send a structured event over the LiveKit data channel."""
        import json

        try:
            payload = json.dumps(event.model_dump(exclude_none=True)).encode("utf-8")
            await self.room.local_participant.publish_data(payload, topic=self._data_topic)
        except Exception as exc:  # pragma: no cover - data channel optional
            logger.debug("LiveKitTransport: failed to publish event: %s", exc)

    async def close(self) -> None:
        """Disconnect from the room."""
        try:
            await self.room.disconnect()
        except Exception:  # pragma: no cover
            pass
