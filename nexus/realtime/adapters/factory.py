"""Build media adapters from config (provider name -> adapter class)."""

from __future__ import annotations

from nexus.realtime.adapters.stt.base import STTAdapter
from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.adapters.vad.base import VADAdapter
from nexus.realtime.config import STTConfig, TTSConfig, VADConfig


def build_stt(config: STTConfig) -> STTAdapter:
    """Instantiate an STT adapter for the configured provider."""
    provider = config.provider.lower()
    if provider in ("mock", "test"):
        from nexus.realtime.adapters.stt.mock import MockSTT

        return MockSTT(config)
    if provider in ("openai", "whisper"):
        from nexus.realtime.adapters.stt.openai import OpenAISTT

        return OpenAISTT(config)
    if provider == "deepgram":
        from nexus.realtime.adapters.stt.deepgram import DeepgramSTT

        return DeepgramSTT(config)
    raise ValueError(f"Unknown STT provider: {config.provider!r}")


def build_tts(config: TTSConfig) -> TTSAdapter:
    """Instantiate a TTS adapter for the configured provider."""
    provider = config.provider.lower()
    if provider in ("mock", "test"):
        from nexus.realtime.adapters.tts.mock import MockTTS

        return MockTTS(config)
    if provider == "openai":
        from nexus.realtime.adapters.tts.openai import OpenAITTS

        return OpenAITTS(config)
    raise ValueError(f"Unknown TTS provider: {config.provider!r}")


def build_vad(config: VADConfig) -> VADAdapter:
    """Instantiate a VAD adapter for the configured provider."""
    provider = config.provider.lower()
    if provider in ("energy", "mock", "test"):
        from nexus.realtime.adapters.vad.energy import EnergyVAD

        return EnergyVAD(config)
    if provider == "silero":
        try:
            from nexus.realtime.adapters.vad.silero import SileroVAD
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "Silero VAD requires extra dependencies; install torch/silero-vad."
            ) from exc
        return SileroVAD(config)
    raise ValueError(f"Unknown VAD provider: {config.provider!r}")
