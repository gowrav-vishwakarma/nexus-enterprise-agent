"""G.711 mu-law codec and a simple PCM16 downsampler.

Python 3.13 removed the ``audioop`` module, so telephony (8 kHz mu-law, used by
Twilio Media Streams / most SIP carriers) needs its own codec. These functions
are pure Python and operate on little-endian PCM16 bytes.
"""

from __future__ import annotations

_BIAS = 0x84
_CLIP = 32635


def _encode_sample(sample: int) -> int:
    """Encode one signed 16-bit PCM sample to an 8-bit mu-law byte."""
    sign = 0x80 if sample < 0 else 0x00
    if sample < 0:
        sample = -sample
    if sample > _CLIP:
        sample = _CLIP
    sample += _BIAS

    exponent = 7
    mask = 0x4000
    while exponent > 0 and not (sample & mask):
        exponent -= 1
        mask >>= 1

    mantissa = (sample >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa)) & 0xFF


def _decode_sample(ulaw_byte: int) -> int:
    """Decode one 8-bit mu-law byte to a signed 16-bit PCM sample."""
    ulaw_byte = ~ulaw_byte & 0xFF
    sign = ulaw_byte & 0x80
    exponent = (ulaw_byte >> 4) & 0x07
    mantissa = ulaw_byte & 0x0F
    sample = ((mantissa << 3) + _BIAS) << exponent
    sample -= _BIAS
    return -sample if sign else sample


def pcm16_to_ulaw(pcm: bytes) -> bytes:
    """Convert little-endian PCM16 bytes to mu-law bytes."""
    out = bytearray(len(pcm) // 2)
    for i in range(len(out)):
        sample = int.from_bytes(pcm[2 * i : 2 * i + 2], "little", signed=True)
        out[i] = _encode_sample(sample)
    return bytes(out)


def ulaw_to_pcm16(ulaw: bytes) -> bytes:
    """Convert mu-law bytes to little-endian PCM16 bytes."""
    out = bytearray(len(ulaw) * 2)
    for i, byte in enumerate(ulaw):
        sample = _decode_sample(byte)
        out[2 * i : 2 * i + 2] = int(sample).to_bytes(2, "little", signed=True)
    return bytes(out)


def downsample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Naive integer-decimation downsampler for PCM16 (no anti-aliasing).

    Good enough to feed TTS output to an 8 kHz telephony leg. For higher quality
    use a real resampler (e.g. soxr) in production.
    """
    if src_rate == dst_rate or src_rate <= 0 or dst_rate <= 0:
        return pcm
    if dst_rate > src_rate:
        return pcm  # upsampling not supported here
    step = src_rate / dst_rate
    samples = len(pcm) // 2
    out = bytearray()
    pos = 0.0
    while int(pos) < samples:
        i = int(pos)
        out += pcm[2 * i : 2 * i + 2]
        pos += step
    return bytes(out)
