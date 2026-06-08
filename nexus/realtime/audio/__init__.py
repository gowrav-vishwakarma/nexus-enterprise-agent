"""Audio codecs/helpers for telephony (pure-Python; no audioop dependency)."""

from nexus.realtime.audio.mulaw import (
    pcm16_to_ulaw,
    ulaw_to_pcm16,
    downsample_pcm16,
)
from nexus.realtime.audio.wav import merge_wav_chunks

__all__ = ["pcm16_to_ulaw", "ulaw_to_pcm16", "downsample_pcm16", "merge_wav_chunks"]
