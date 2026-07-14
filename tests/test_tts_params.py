"""Tests for TTS speed stretch and param pass-through."""

import numpy as np

from nexus.realtime.config import TTSConfig
from nexus.server.engines.tts_params import apply_speed, coerce_params, stringify_params


def test_apply_speed_faster_shortens():
    audio = np.ones(1000, dtype=np.float32)
    out = apply_speed(audio, 2.0)
    assert len(out) == 500


def test_apply_speed_slower_lengthens():
    audio = np.ones(1000, dtype=np.float32)
    out = apply_speed(audio, 0.5)
    assert len(out) == 2000


def test_apply_speed_noop():
    audio = np.ones(100, dtype=np.float32)
    assert apply_speed(audio, 1.0) is audio or len(apply_speed(audio, 1.0)) == 100


def test_tts_config_merges_params_over_extra():
    cfg = TTSConfig(
        provider="mock",
        speed=1.25,
        extra={"a": 1, "shared": "old"},
        params={"shared": "new", "b": True},
    )
    assert cfg.effective_params() == {"a": 1, "shared": "new", "b": True}
    assert cfg.speed == 1.25


def test_stringify_and_coerce_roundtrip():
    raw = stringify_params({"n": 3, "f": 1.5, "ok": True, "s": "hi"})
    assert raw == {"n": "3", "f": "1.5", "ok": "True", "s": "hi"}
    back = coerce_params(raw)
    assert back["n"] == 3
    assert back["f"] == 1.5
    assert back["ok"] is True
    assert back["s"] == "hi"
