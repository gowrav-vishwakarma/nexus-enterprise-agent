"""Text-to-speech adapters."""

from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.adapters.tts.mock import MockTTS

__all__ = ["TTSAdapter", "MockTTS"]
