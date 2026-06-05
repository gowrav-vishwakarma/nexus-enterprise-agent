"""Energy-based VAD: a dependency-free turn detector for PCM16 audio.

Computes normalized RMS energy per frame. Speech starts when energy crosses the
threshold; a turn ends after ``silence_ms`` of sub-threshold energy. Good enough
for IVR/half-duplex and as a default for full-duplex; swap in Silero for higher
accuracy when needed.
"""

from __future__ import annotations

import math
from typing import Optional

from nexus.realtime.adapters.vad.base import VADAdapter, VADEvent
from nexus.realtime.config import VADConfig

_INT16_MAX = 32768.0


def _frame_rms(frame: bytes) -> float:
    """Normalized RMS (0..1) of a little-endian PCM16 frame."""
    if len(frame) < 2:
        return 0.0
    count = len(frame) // 2
    total = 0.0
    for i in range(0, count * 2, 2):
        sample = int.from_bytes(frame[i : i + 2], "little", signed=True)
        total += sample * sample
    rms = math.sqrt(total / count)
    return rms / _INT16_MAX


class EnergyVAD(VADAdapter):
    """Threshold + hangover turn detector."""

    def __init__(self, config: Optional[VADConfig] = None) -> None:
        super().__init__(config or VADConfig(provider="energy"))
        self._in_speech = False
        self._buffer = bytearray()
        self._silence_ms = 0.0
        self._speech_ms = 0.0
        self._sample_rate = self.config.sample_rate

    def _frame_ms(self, frame: bytes) -> float:
        samples = len(frame) / 2
        return (samples / self._sample_rate) * 1000.0 if self._sample_rate else 0.0

    def process_frame(self, frame: bytes) -> Optional[VADEvent]:
        """Feed one frame; return SPEECH_START/SPEECH_END at boundaries."""
        energy = _frame_rms(frame)
        frame_ms = self._frame_ms(frame)
        is_speech = energy >= self.config.threshold

        if is_speech:
            self._silence_ms = 0.0
            if not self._in_speech:
                self._in_speech = True
                self._speech_ms = 0.0
                self._buffer = bytearray()
                self._buffer.extend(frame)
                return VADEvent.SPEECH_START
            self._speech_ms += frame_ms
            self._buffer.extend(frame)
            return None

        # Sub-threshold frame.
        if self._in_speech:
            self._buffer.extend(frame)
            self._silence_ms += frame_ms
            if self._silence_ms >= self.config.silence_ms:
                if self._speech_ms >= self.config.min_speech_ms:
                    self._in_speech = False
                    return VADEvent.SPEECH_END
                # Too short to count as a turn; discard.
                self._in_speech = False
                self._buffer = bytearray()
        return None

    def take_utterance(self) -> bytes:
        """Return buffered audio and clear it."""
        data = bytes(self._buffer)
        self._buffer = bytearray()
        return data

    def reset(self) -> None:
        """Reset detector state."""
        self._in_speech = False
        self._buffer = bytearray()
        self._silence_ms = 0.0
        self._speech_ms = 0.0
