"""Audio codecs/helpers for telephony (pure-Python; no audioop dependency)."""

from nexus.realtime.audio.mulaw import (
    pcm16_to_ulaw,
    ulaw_to_pcm16,
    downsample_pcm16,
)

__all__ = ["pcm16_to_ulaw", "ulaw_to_pcm16", "downsample_pcm16"]
