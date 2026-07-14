"""Silero VAD engine with per-session state."""

from __future__ import annotations

import logging

import numpy as np

from nexus.server.engines.base import EngineMeta, VADEngine, VADSession

logger = logging.getLogger(__name__)

CHUNK = 512
HYSTERESIS = 0.15


class _SileroSession(VADSession):
    def __init__(self, model, threshold: float, min_silence_ms: int, min_speech_ms: int) -> None:
        self._model = model
        self._threshold = threshold
        self._min_silence_samples = int(min_silence_ms * 16)
        self._min_speech_samples = int(min_speech_ms * 16)
        self._sample_rate = 16000
        self._chunk_buf = np.array([], dtype=np.float32)
        self._speaking = False
        self._silence = 0
        self._speech = 0
        self._accum: list[bytes] = []

    def reset(self) -> None:
        self._chunk_buf = np.array([], dtype=np.float32)
        self._speaking = False
        self._silence = 0
        self._speech = 0
        self._accum.clear()
        try:
            self._model.reset_states()
        except Exception:
            pass

    def process_frame(self, frame: bytes) -> str | None:
        import torch

        if not frame:
            return None
        floats = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        self._chunk_buf = np.concatenate([self._chunk_buf, floats])
        event = None
        while len(self._chunk_buf) >= CHUNK:
            chunk = self._chunk_buf[:CHUNK]
            self._chunk_buf = self._chunk_buf[CHUNK:]
            with torch.no_grad():
                prob = self._model(torch.from_numpy(chunk), self._sample_rate).item()
            bar = self._threshold - HYSTERESIS if self._speaking else self._threshold
            if prob >= bar:
                if not self._speaking:
                    self._speaking = True
                    self._speech = 0
                    self._silence = 0
                    self._accum = [frame]
                    event = "speech_start"
                else:
                    self._speech += CHUNK
                    self._accum.append(frame)
                    self._silence = 0
            elif self._speaking:
                self._silence += CHUNK
                self._accum.append(frame)
                if (
                    self._silence >= self._min_silence_samples
                    and self._speech >= self._min_speech_samples
                ):
                    self._speaking = False
                    event = "speech_end"
        return event

    def take_utterance(self) -> bytes:
        data = b"".join(self._accum)
        self._accum.clear()
        return data


class SileroEngine(VADEngine):
    meta = EngineMeta(id="silero", label="Silero VAD", kind="vad", sample_rate=16000)

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_ms: int = 300,
        min_speech_ms: int = 250,
    ) -> None:
        self._threshold = threshold
        self._min_silence_ms = min_silence_ms
        self._min_speech_ms = min_speech_ms
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, **kwargs) -> None:
        if self._model is not None:
            return
        import torch

        logger.info("Loading Silero VAD")
        model, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True, verbose=False)
        model.eval()
        self._model = model

    def create_session(self) -> VADSession:
        self.load()
        return _SileroSession(
            self._model,
            self._threshold,
            self._min_silence_ms,
            self._min_speech_ms,
        )
