"""Indic-Conformer STT engine (lazy torch import)."""

from __future__ import annotations

import logging
import time

import numpy as np

from nexus.server.engines.base import EngineMeta, STTEngine

logger = logging.getLogger(__name__)
TARGET_SR = 16_000


class ConformerEngine(STTEngine):
    meta = EngineMeta(
        id="conformer",
        label="Indic-Conformer 600M",
        kind="stt",
        languages=("hi", "gu", "ta", "te", "kn", "bn", "mr", "ml", "pa", "or", "en"),
        sample_rate=TARGET_SR,
    )

    def __init__(
        self,
        model_id: str = "ai4bharat/indic-conformer-600m-multilingual",
        device: str = "cpu",
        decoding: str = "rnnt",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._decoding = decoding
        self._model = None
        self._torch = None
        self._taf = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, **kwargs) -> None:
        if self._model is not None:
            return
        import torch
        import torchaudio.functional as taf
        from transformers import AutoModel

        logger.info("Loading STT %s on %s", self._model_id, self._device)
        start = time.monotonic()
        model = AutoModel.from_pretrained(self._model_id, trust_remote_code=True)
        try:
            model = model.to(self._device)
        except Exception:
            pass
        model.eval()
        self._model = model
        self._torch = torch
        self._taf = taf
        logger.info("STT ready in %.1fs", time.monotonic() - start)

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str) -> str:
        self.load()
        torch = self._torch
        wav = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)
        if sample_rate != TARGET_SR:
            wav = self._taf.resample(wav, sample_rate, TARGET_SR)
        with torch.no_grad():
            out = self._model(wav, language, self._decoding)
        if isinstance(out, (list, tuple)):
            out = out[0] if out else ""
        return str(out).strip()
