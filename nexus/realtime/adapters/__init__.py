"""Media adapters: STT, TTS, VAD, and S2S.

Concrete provider clients (openai, deepgram, websockets, ...) are imported lazily
inside each adapter so this package imports cleanly without optional extras.
"""

from nexus.realtime.adapters.factory import (
    build_stt,
    build_tts,
    build_vad,
)
from nexus.realtime.adapters.stt.base import STTAdapter, STTResult
from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.adapters.vad.base import VADAdapter, VADEvent

__all__ = [
    "STTAdapter",
    "STTResult",
    "TTSAdapter",
    "VADAdapter",
    "VADEvent",
    "build_stt",
    "build_tts",
    "build_vad",
]
