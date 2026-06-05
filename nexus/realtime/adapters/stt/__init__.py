"""Speech-to-text adapters."""

from nexus.realtime.adapters.stt.base import STTAdapter, STTResult
from nexus.realtime.adapters.stt.mock import MockSTT

__all__ = ["STTAdapter", "STTResult", "MockSTT"]
