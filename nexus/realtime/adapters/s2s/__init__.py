"""Speech-to-speech (realtime model) adapters."""

from nexus.realtime.adapters.s2s.base import SpeechToSpeechAdapter
from nexus.realtime.adapters.s2s.mock import MockS2S

__all__ = ["SpeechToSpeechAdapter", "MockS2S"]


def __getattr__(name: str):
    """Lazily expose the OpenAI Realtime adapter (needs websockets)."""
    if name == "OpenAIRealtimeS2S":
        from nexus.realtime.adapters.s2s.openai_realtime import OpenAIRealtimeS2S

        return OpenAIRealtimeS2S
    raise AttributeError(f"module 'nexus.realtime.adapters.s2s' has no attribute {name!r}")
