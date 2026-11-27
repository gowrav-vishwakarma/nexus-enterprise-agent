import asyncio
import sys
import time
import types

import pytest

from nexus.server.engines.faster_whisper import FasterWhisperLIDEngine
from nexus.server.proto import media_pb2
from nexus.server.services.base import HealthServicer
from nexus.server.services.lid_server import LidServicer


class _SlowWhisper:
    """Stands in for faster_whisper.WhisperModel: 0.3 s per detection."""

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def detect_language(self, audio):
        time.sleep(0.3)
        return "hi", 0.9, None


@pytest.fixture(autouse=True)
def fake_whisper(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=_SlowWhisper))


async def _two_callers_at_once(engine) -> float:
    engine.load()
    lid = LidServicer(engine, HealthServicer("lid", "faster_whisper"))
    req = media_pb2.LidRequest(pcm=b"\0\0" * 1600, sample_rate=16000, fallback_language="en")
    t0 = time.monotonic()
    await asyncio.gather(lid.DetectLanguage(req, None), lid.DetectLanguage(req, None))
    return time.monotonic() - t0


@pytest.mark.asyncio
async def test_one_worker_keeps_callers_in_line():
    assert await _two_callers_at_once(FasterWhisperLIDEngine()) >= 0.55  # 2 x 0.3 s, serialized


@pytest.mark.asyncio
async def test_workers_detect_for_callers_in_parallel():
    engine = FasterWhisperLIDEngine(num_workers="4")  # as it arrives from ${ENV:...}
    assert await _two_callers_at_once(engine) < 0.5
    assert engine._model.kwargs["num_workers"] == 4
