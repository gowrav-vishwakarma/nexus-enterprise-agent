"""Mock engines for tests (no GPU, no torch)."""

from __future__ import annotations

import struct
from collections.abc import Iterator

from typing import Any

import numpy as np

from nexus.server.engines.base import (
    EngineMeta,
    LIDEngine,
    STTEngine,
    TTSEngine,
    VADEngine,
    VADSession,
)


class MockSTTEngine(STTEngine):
    meta = EngineMeta(id="mock", label="Mock STT", kind="stt", languages=("en", "hi"))

    def __init__(self, **kwargs: Any) -> None:
        pass

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str) -> str:
        duration = len(audio) / max(sample_rate, 1)
        return f"mock transcript ({language}, {duration:.1f}s)"


class MockTTSEngine(TTSEngine):
    meta = EngineMeta(id="mock", label="Mock TTS", kind="tts", sample_rate=24000)
    sample_rate = 24000

    def __init__(self, **kwargs: Any) -> None:
        pass

    def synthesize(
        self,
        text: str,
        language: str,
        voice: str | None = None,
        *,
        speed: float = 1.0,
        params: dict | None = None,
    ) -> np.ndarray:
        # Audible test tone so Voice Lab / mock gRPC TTS is hearable (not silence).
        sr = self.sample_rate
        duration = max(0.25, min(2.5, len(text) * 0.04))
        n = int(sr * duration)
        t = np.arange(n, dtype=np.float32) / sr
        audio = (0.25 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        from nexus.server.engines.tts_params import apply_speed

        return apply_speed(audio, speed)

    def synthesize_stream(
        self,
        text: str,
        language: str,
        voice: str | None = None,
        *,
        chunk_s: float = 0.35,
        should_stop=None,
        speed: float = 1.0,
        params: dict | None = None,
    ) -> Iterator[np.ndarray]:
        audio = self.synthesize(text, language, voice, speed=speed, params=params)
        chunk_samples = int(self.sample_rate * chunk_s)
        for start in range(0, len(audio), chunk_samples):
            if should_stop and should_stop():
                break
            yield audio[start : start + chunk_samples]


class _MockVADSession(VADSession):
    def __init__(self, threshold_bytes: int = 3200) -> None:
        self._threshold = threshold_bytes
        self._buffer = bytearray()
        self._speaking = False
        self._accum: list[bytes] = []

    def process_frame(self, frame: bytes) -> str | None:
        if not frame:
            return None
        self._buffer.extend(frame)
        if not self._speaking and len(self._buffer) >= self._threshold:
            self._speaking = True
            self._accum = [bytes(self._buffer)]
            self._buffer.clear()
            return "speech_start"
        if self._speaking:
            self._accum.append(frame)
            if len(self._accum) > 8:
                self._speaking = False
                return "speech_end"
        return None

    def take_utterance(self) -> bytes:
        data = b"".join(self._accum)
        self._accum.clear()
        return data

    def reset(self) -> None:
        self._buffer.clear()
        self._accum.clear()
        self._speaking = False


class MockVADEngine(VADEngine):
    meta = EngineMeta(id="mock", label="Mock VAD", kind="vad", sample_rate=16000)

    def __init__(self, **kwargs: Any) -> None:
        pass

    def create_session(self) -> VADSession:
        return _MockVADSession()


class MockLIDEngine(LIDEngine):
    meta = EngineMeta(
        id="mock", label="Mock LID", kind="lid", languages=("en", "hi", "gu")
    )

    def __init__(self, **kwargs: Any) -> None:
        pass

    def detect(
        self, audio: np.ndarray, sample_rate: int, fallback_language: str = "hi"
    ) -> tuple[str, float, str | None]:
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if len(audio) else 0.0
        if rms > 0.01:
            return "hi", 0.9, None
        return fallback_language, 0.5, None


def float32_to_pcm16(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    ints = (clipped * 32767.0).astype(np.int16)
    return ints.tobytes()


def pcm16_to_float32(pcm: bytes) -> np.ndarray:
    if not pcm:
        return np.array([], dtype=np.float32)
    ints = np.frombuffer(pcm, dtype=np.int16)
    return ints.astype(np.float32) / 32768.0
