"""TTS helpers: speed stretch and param serialization."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np


def apply_speed(audio: np.ndarray, speed: float) -> np.ndarray:
    """Time-stretch mono float audio by ``speed`` (1.0 = unchanged).

    Used when the engine has no native rate control (e.g. Indic Parler).
    ``speed > 1`` speaks faster (shorter); ``speed < 1`` speaks slower.
    """
    try:
        rate = float(speed)
    except (TypeError, ValueError):
        return audio
    if rate <= 0 or abs(rate - 1.0) < 1e-3 or audio is None or len(audio) == 0:
        return audio
    wav = np.asarray(audio, dtype=np.float32).reshape(-1)
    new_len = max(1, int(round(len(wav) / rate)))
    if new_len == len(wav):
        return wav
    x_old = np.linspace(0.0, 1.0, num=len(wav), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(x_new, x_old, wav).astype(np.float32)


def stringify_params(params: Mapping[str, Any] | None) -> dict[str, str]:
    """Flatten engine params to string map for gRPC ``TtsRequest.params``."""
    if not params:
        return {}
    out: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        out[str(key)] = value if isinstance(value, str) else str(value)
    return out


def coerce_params(raw: Mapping[str, str] | None) -> dict[str, Any]:
    """Best-effort parse of string params back to bool/int/float when obvious."""
    if not raw:
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        low = value.lower()
        if low in ("true", "false"):
            out[key] = low == "true"
            continue
        try:
            if "." in value:
                out[key] = float(value)
            else:
                out[key] = int(value)
            continue
        except ValueError:
            out[key] = value
    return out
