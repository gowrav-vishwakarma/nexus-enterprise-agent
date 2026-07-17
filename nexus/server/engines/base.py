"""Engine plugin contracts and auto-discovery registry."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

logger = logging.getLogger(__name__)

EngineKind = Literal["stt", "tts", "vad", "lid"]


@dataclass(frozen=True)
class EngineMeta:
    id: str
    label: str
    kind: EngineKind
    languages: tuple[str, ...] = ()
    sample_rate: int = 16000
    extra: dict[str, Any] = field(default_factory=dict)


class BaseEngine(ABC):
    meta: EngineMeta

    def load(self, **kwargs: Any) -> None:
        """Load model weights. Idempotent."""

    def unload(self) -> None:
        """Release resources."""

    @property
    def loaded(self) -> bool:
        return False


class STTEngine(BaseEngine):
    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str) -> str:
        raise NotImplementedError


class TTSEngine(BaseEngine):
    sample_rate: int = 24000

    @abstractmethod
    def synthesize(
        self,
        text: str,
        language: str,
        voice: str | None = None,
        *,
        speed: float = 1.0,
        params: dict | None = None,
    ) -> np.ndarray:
        raise NotImplementedError

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
        yield self.synthesize(
            text, language, voice, speed=speed, params=params
        )


class VADEngine(BaseEngine):
    @abstractmethod
    def create_session(self) -> "VADSession":
        raise NotImplementedError


class VADSession(ABC):
    @abstractmethod
    def process_frame(self, frame: bytes) -> str | None:
        """Return 'speech_start', 'speech_end', or None."""

    @abstractmethod
    def take_utterance(self) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError


class LIDEngine(BaseEngine):
    @abstractmethod
    def detect(
        self, audio: np.ndarray, sample_rate: int, fallback_language: str = "hi"
    ) -> tuple[str, float, str | None]:
        """Return (language, confidence, english_text_or_none)."""
        raise NotImplementedError


_REGISTRY: dict[EngineKind, dict[str, type[BaseEngine]]] = {
    "stt": {},
    "tts": {},
    "vad": {},
    "lid": {},
}
_DISCOVERED = False


def _kind_for(cls: type) -> EngineKind | None:
    if issubclass(cls, STTEngine) and cls is not STTEngine:
        return "stt"
    if issubclass(cls, TTSEngine) and cls is not TTSEngine:
        return "tts"
    if issubclass(cls, VADEngine) and cls is not VADEngine:
        return "vad"
    if issubclass(cls, LIDEngine) and cls is not LIDEngine:
        return "lid"
    return None


def _discover() -> None:
    global _DISCOVERED
    if _DISCOVERED:
        return
    pkg_name = "nexus.server.engines"
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception as exc:
        logger.warning("Engine package unavailable: %s", exc)
        return
    path = getattr(pkg, "__path__", None)
    if path is None:
        return
    for mod in pkgutil.iter_modules(path):
        if mod.name.startswith("_"):
            continue
        full = f"{pkg_name}.{mod.name}"
        try:
            module = importlib.import_module(full)
        except Exception as exc:
            logger.warning("Failed to import engine %s: %s", full, exc)
            continue
        for attr in vars(module).values():
            if not isinstance(attr, type) or not issubclass(attr, BaseEngine):
                continue
            kind = _kind_for(attr)
            meta = getattr(attr, "meta", None)
            if kind is None or not isinstance(meta, EngineMeta):
                continue
            _REGISTRY[kind][meta.id] = attr
    _DISCOVERED = True


def create(kind: EngineKind, engine_id: str, **kwargs: Any) -> BaseEngine:
    _discover()
    cls = _REGISTRY[kind].get(engine_id)
    if cls is None:
        known = ", ".join(sorted(_REGISTRY[kind])) or "(none)"
        raise KeyError(f"Unknown {kind} engine {engine_id!r}; known: {known}")
    engine = cls(**kwargs)  # type: ignore[call-arg]
    engine.load()
    return engine


def available(kind: EngineKind) -> list[EngineMeta]:
    _discover()
    out: list[EngineMeta] = []
    for cls in _REGISTRY[kind].values():
        meta = getattr(cls, "meta", None)
        if isinstance(meta, EngineMeta):
            out.append(meta)
    return sorted(out, key=lambda m: m.id)
