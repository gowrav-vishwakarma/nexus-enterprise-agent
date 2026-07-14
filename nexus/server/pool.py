"""Shared engine pool with optional TTS replicas."""

from __future__ import annotations

import logging
import threading
from typing import Any

from nexus.server.engines.base import BaseEngine, EngineKind, TTSEngine, create

logger = logging.getLogger(__name__)


class EnginePool:
    """One loaded engine per kind+id (shared weights)."""

    def __init__(self) -> None:
        self._engines: dict[tuple[EngineKind, str], BaseEngine] = {}
        self._lock = threading.Lock()

    def get(self, kind: EngineKind, engine_id: str, **kwargs: Any) -> BaseEngine:
        key = (kind, engine_id)
        with self._lock:
            if key not in self._engines:
                logger.info("EnginePool loading %s/%s", kind, engine_id)
                self._engines[key] = create(kind, engine_id, **kwargs)
            return self._engines[key]

    def unload(self, kind: EngineKind, engine_id: str) -> None:
        key = (kind, engine_id)
        with self._lock:
            eng = self._engines.pop(key, None)
            if eng is not None:
                eng.unload()


class TTSReplicaPool:
    """N independent TTS engine instances for concurrent synthesis."""

    def __init__(self, engine_id: str, replicas: int = 1, **kwargs: Any) -> None:
        self._replicas: list[TTSEngine] = []
        for i in range(replicas):
            eng = create("tts", engine_id, **kwargs)
            self._replicas.append(eng)  # type: ignore[arg-type]
        self._index = 0
        self._lock = threading.Lock()

    def acquire(self) -> TTSEngine:
        with self._lock:
            eng = self._replicas[self._index % len(self._replicas)]
            self._index += 1
            return eng

    @property
    def sample_rate(self) -> int:
        return self._replicas[0].sample_rate if self._replicas else 24000
