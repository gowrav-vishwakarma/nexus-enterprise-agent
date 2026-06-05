"""Kyutai Moshi speech-to-speech adapter (real model, no mock).

Connects to a self-hosted Moshi server (run separately, e.g. in local-ai-stack)
over its binary WebSocket protocol and bridges it to the framework's plain-PCM
audio contract. All Moshi/Opus specifics live here, so the pipeline, transports
and browser keep speaking simple PCM16 — adding another S2S model later is just a
new adapter + provider name.

Moshi wire protocol (``/api/chat``):
  - handshake: client sends 9 bytes ``<B I I>`` (type=0, proto=0, model=0)
  - audio:     ``0x01`` + Opus bytes (bidirectional, 24 kHz)
  - text:      ``0x02`` + UTF-8 (server -> client, Moshi's inner monologue)
  - error:     ``0x05`` + UTF-8 (server -> client)

Optional deps (install the ``moshi`` extra): ``websockets``, ``sphn``, ``numpy``.
No torch here — the model itself runs in the separate Moshi server.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from nexus.realtime.adapters.s2s.base import SpeechToSpeechAdapter
from nexus.realtime.config import S2SConfig
from nexus.realtime.events import RealtimeStreamEvent

_MOSHI_SAMPLE_RATE = 24000
_KIND_HANDSHAKE = 0x00
_KIND_AUDIO = 0x01
_KIND_TEXT = 0x02
_KIND_ERROR = 0x05


def _require_deps():
    try:
        import numpy as np  # noqa: F401
        import sphn  # noqa: F401
        import websockets  # noqa: F401
    except ImportError as exc:  # pragma: no cover - optional dep
        raise ImportError(
            "The Moshi S2S adapter needs the 'moshi' extra: "
            "pip install 'nexus-enterprise-agent[moshi]' (websockets, sphn, numpy). "
            "The Moshi model itself runs in a separate server (see local-ai-stack)."
        ) from exc


class MoshiS2S(SpeechToSpeechAdapter):
    """Drive a self-hosted Kyutai Moshi server for full-duplex speech-to-speech."""

    def __init__(self, config: S2SConfig, **kwargs) -> None:
        super().__init__(config, **kwargs)
        base = (config.base_url or "ws://localhost:8998").rstrip("/")
        self._url = base if base.endswith("/api/chat") else f"{base}/api/chat"

    @staticmethod
    def _pcm16_to_f32(data: bytes):
        import numpy as np

        return np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0

    @staticmethod
    def _f32_to_pcm16(arr) -> bytes:
        import numpy as np

        return (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    async def run_audio(
        self, audio_in: AsyncIterator[bytes]
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Stream PCM16 (24 kHz mono) into Moshi and yield PCM/text events."""
        _require_deps()
        import sphn
        import websockets

        writer = sphn.OpusStreamWriter(_MOSHI_SAMPLE_RATE)
        reader = sphn.OpusStreamReader(_MOSHI_SAMPLE_RATE)

        async with websockets.connect(self._url, max_size=None) as ws:
            # The Moshi server sends its own b"\x00" handshake and then expects
            # 0x01+opus audio frames; the client sends no handshake.

            async def _send_audio() -> None:
                try:
                    async for pcm in audio_in:
                        if not pcm:
                            continue
                        # sphn returns the encoded opus bytes directly.
                        opus = writer.append_pcm(self._pcm16_to_f32(pcm))
                        if opus is not None and len(opus):
                            await ws.send(bytes([_KIND_AUDIO]) + opus)
                except (asyncio.CancelledError, websockets.ConnectionClosed):
                    pass
                finally:
                    # Input ended (session over): close cleanly so the Moshi
                    # server releases its per-connection lock for the next caller.
                    try:
                        await ws.close()
                    except Exception:  # noqa: BLE001
                        pass

            sender = asyncio.create_task(_send_audio())
            yield RealtimeStreamEvent(
                event_type="session_started", data={"modality": "voice_s2s", "provider": "moshi"}
            )
            try:
                async for message in ws:
                    if isinstance(message, str) or not message:
                        continue
                    kind, payload = message[0], message[1:]
                    if kind == _KIND_AUDIO:
                        # sphn returns the decoded PCM directly.
                        pcm = reader.append_bytes(payload)
                        if pcm is not None and len(pcm):
                            yield RealtimeStreamEvent.audio_chunk(self._f32_to_pcm16(pcm))
                    elif kind == _KIND_TEXT:
                        text = payload.decode("utf-8", errors="replace")
                        if text:
                            yield RealtimeStreamEvent.text_delta(text)
                    elif kind == _KIND_ERROR:
                        yield RealtimeStreamEvent(
                            event_type="error",
                            data={"message": payload.decode("utf-8", errors="replace")},
                        )
            finally:
                # Stop the sender and let it fully unwind before the socket
                # closes, so we never close mid-send (avoids a teardown race).
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
        yield RealtimeStreamEvent(event_type="turn_end", data={"provider": "moshi"})

    async def run_text(self, text: str) -> AsyncIterator[RealtimeStreamEvent]:
        """Moshi is audio-native; text-only turns aren't supported."""
        yield RealtimeStreamEvent(
            event_type="error",
            content="Moshi is a speech-to-speech model; use the audio path.",
            data={"unsupported": "run_text"},
        )
