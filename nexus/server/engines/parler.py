"""Indic Parler TTS engine (lazy torch import)."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

import numpy as np

from nexus.server.engines.base import EngineMeta, TTSEngine

logger = logging.getLogger(__name__)

_DEFAULT_VOICE = (
    "Divya speaks in a clear, expressive voice at a moderate pace, "
    "in a very quiet environment."
)


class ParlerEngine(TTSEngine):
    meta = EngineMeta(
        id="parler",
        label="Indic Parler TTS",
        kind="tts",
        languages=("hi", "gu", "ta", "te", "kn", "bn", "mr", "ml", "pa", "or", "en"),
        sample_rate=44100,
    )
    sample_rate = 44100

    def __init__(
        self,
        model_id: str = "ai4bharat/indic-parler-tts",
        device: str = "cuda",
        dtype: str = "bfloat16",
        attn_implementation: str = "eager",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._dtype_name = dtype
        self._attn = attn_implementation
        self._model = None
        self._tok = None
        self._desc_tok = None
        self._torch = None
        self._desc_cache: dict[str, tuple] = {}

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self, **kwargs) -> None:
        if self._model is not None:
            return
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        torch_dtype = getattr(torch, self._dtype_name, torch.float32)
        logger.info("Loading TTS %s on %s", self._model_id, self._device)
        start = time.monotonic()
        model = ParlerTTSForConditionalGeneration.from_pretrained(
            self._model_id, attn_implementation=self._attn
        ).to(self._device, dtype=torch_dtype)
        model.eval()
        self._model = model
        self._tok = AutoTokenizer.from_pretrained(self._model_id)
        self._desc_tok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
        self.sample_rate = int(getattr(model.config, "sampling_rate", 44100))
        self.meta = EngineMeta(
            id="parler",
            label="Indic Parler TTS",
            kind="tts",
            languages=self.meta.languages,
            sample_rate=self.sample_rate,
        )
        self._torch = torch
        logger.info("TTS ready in %.1fs @ %dHz", time.monotonic() - start, self.sample_rate)

    def _voice_desc(self, voice: str | None) -> str:
        return voice or _DEFAULT_VOICE

    def synthesize(self, text: str, language: str, voice: str | None = None) -> np.ndarray:
        self.load()
        torch = self._torch
        description = self._voice_desc(voice)
        cached = self._desc_cache.get(description)
        if cached is None:
            desc_enc = self._desc_tok(description, return_tensors="pt")
            cached = (
                desc_enc.input_ids.to(self._device),
                desc_enc.attention_mask.to(self._device),
            )
            self._desc_cache[description] = cached
        desc_ids, desc_mask = cached
        prompt_enc = self._tok(text, return_tensors="pt")
        with torch.no_grad():
            gen = self._model.generate(
                input_ids=desc_ids,
                attention_mask=desc_mask,
                prompt_input_ids=prompt_enc.input_ids.to(self._device),
                prompt_attention_mask=prompt_enc.attention_mask.to(self._device),
            )
        return gen.to(torch.float32).cpu().numpy().squeeze()

    def synthesize_stream(
        self,
        text: str,
        language: str,
        voice: str | None = None,
        *,
        chunk_s: float = 0.35,
        should_stop=None,
    ) -> Iterator[np.ndarray]:
        self.load()
        torch = self._torch
        from threading import Thread

        from parler_tts import ParlerTTSStreamer
        from transformers.generation.stopping_criteria import StoppingCriteria, StoppingCriteriaList

        description = self._voice_desc(voice)
        frame_rate = getattr(self._model.audio_encoder.config, "frame_rate", 86)
        play_steps = max(10, int(frame_rate * chunk_s))
        streamer = ParlerTTSStreamer(self._model, device=self._device, play_steps=play_steps)

        cached = self._desc_cache.get(description)
        if cached is None:
            desc_enc = self._desc_tok(description, return_tensors="pt")
            cached = (
                desc_enc.input_ids.to(self._device),
                desc_enc.attention_mask.to(self._device),
            )
            self._desc_cache[description] = cached
        desc_ids, desc_mask = cached
        prompt_enc = self._tok(text, return_tensors="pt")

        class _CancelCriteria(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs) -> bool:
                return bool(should_stop()) if should_stop is not None else False

        def _generate() -> None:
            try:
                with torch.no_grad():
                    self._model.generate(
                        input_ids=desc_ids,
                        attention_mask=desc_mask,
                        prompt_input_ids=prompt_enc.input_ids.to(self._device),
                        prompt_attention_mask=prompt_enc.attention_mask.to(self._device),
                        streamer=streamer,
                        stopping_criteria=StoppingCriteriaList([_CancelCriteria()]),
                    )
            finally:
                try:
                    streamer.audio_queue.put(streamer.stop_signal)
                except Exception:
                    pass

        worker = Thread(target=_generate, daemon=True)
        worker.start()
        try:
            for chunk in streamer:
                if should_stop and should_stop():
                    break
                if chunk is not None and len(chunk) > 0:
                    yield np.asarray(chunk, dtype=np.float32)
        finally:
            worker.join(timeout=30.0)
