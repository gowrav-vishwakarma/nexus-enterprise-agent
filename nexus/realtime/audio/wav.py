"""WAV helpers for stitching TTS sentence chunks."""

from __future__ import annotations

import io
import wave


def merge_wav_chunks(chunks: list[bytes]) -> bytes:
    """Merge multiple WAV byte blobs into one playable WAV file.

    TTS adapters often return one WAV per sentence. Naive ``b"".join`` leaves
    extra RIFF headers in the middle and browsers cannot decode the result.
    """
    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]

    out = io.BytesIO()
    params: tuple[int, int, int, int, int, bytes] | None = None
    frames: list[bytes] = []
    for chunk in chunks:
        with wave.open(io.BytesIO(chunk), "rb") as reader:
            current = reader.getparams()
            if params is None:
                params = current
            elif current[:3] != params[:3]:
                raise ValueError(
                    "WAV chunks have incompatible format "
                    f"(expected {params[:3]}, got {current[:3]})"
                )
            frames.append(reader.readframes(reader.getnframes()))

    if params is None:
        return b""

    with wave.open(out, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(b"".join(frames))
    return out.getvalue()
