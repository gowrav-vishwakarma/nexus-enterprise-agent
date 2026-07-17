"""faster-whisper LID engine (lazy import)."""

from __future__ import annotations

import logging
import time

import numpy as np

from nexus.server.engines.base import EngineMeta, LIDEngine

logger = logging.getLogger(__name__)

INDIC_LANGS = {"hi", "gu", "ta", "te", "kn", "bn", "mr", "ml", "pa", "or"}
SUPPORTED = INDIC_LANGS | {"en"}
DETECT_CAP_SECS = 3.0


class FasterWhisperLIDEngine(LIDEngine):
    meta = EngineMeta(
        id="faster_whisper",
        label="faster-whisper LID",
        kind="lid",
        languages=tuple(sorted(SUPPORTED)),
        sample_rate=16000,
    )

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str | None = None,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type or ("float16" if device == "cuda" else "int8")
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, **kwargs) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        logger.info("Loading Whisper LID %s on %s", self._model_size, self._device)
        start = time.monotonic()
        self._model = WhisperModel(
            self._model_size, device=self._device, compute_type=self._compute_type
        )
        logger.info("LID ready in %.1fs", time.monotonic() - start)

    def detect(
        self, audio: np.ndarray, sample_rate: int, fallback_language: str = "hi"
    ) -> tuple[str, float, str | None]:
        self.load()
        sr = 16_000
        if sample_rate != sr and len(audio):
            ratio = sr / sample_rate
            indices = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
            indices = np.clip(indices, 0, len(audio) - 1)
            audio = audio[indices]
        cap = int(DETECT_CAP_SECS * sr)
        audio_cap = audio[:cap]
        detected, confidence, _ = self._model.detect_language(audio_cap)
        detected = (detected or "").lower()
        confidence = float(confidence or 0.0)

        low_conf = detected not in SUPPORTED or confidence < 0.55
        fallback = (fallback_language or "hi").lower().split("-")[0]
        lang = fallback if low_conf else detected

        # English (whether confidently detected OR resolved via fallback) MUST be
        # transcribed here: Indic-Conformer has no English head, so Whisper is the
        # only English transcript source. Skipping this leaves english_text empty
        # and the caller drops the turn (silent agent). Indic langs are handed to
        # Conformer by the caller, so we return (lang, None) without decoding.
        if lang == "en":
            segments, _ = self._model.transcribe(
                audio, beam_size=1, vad_filter=True, language="en"
            )
            text = " ".join(s.text for s in segments).strip()
            return "en", confidence, text or None
        return lang, confidence, None
