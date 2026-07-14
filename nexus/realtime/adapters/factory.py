"""Build media adapters from config (provider name -> adapter class)."""

from __future__ import annotations

from typing import Optional

from nexus.realtime.adapters.stt.base import STTAdapter
from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.adapters.vad.base import VADAdapter
from nexus.realtime.config import LIDConfig, STTConfig, TTSConfig, VADConfig
from nexus.tools.context import RunContext

_NEXUS_SERVER = frozenset({"nexus_server", "grpc", "nexus"})


# Provider names that all speak the OpenAI /v1/audio/transcriptions API. Point
# `base_url` at any local server (speaches, faster-whisper-server, ...) for a
# fully self-hosted, BYOM, offline-first setup — no paid API required.
_OPENAI_COMPATIBLE_STT = frozenset(
    {"openai", "whisper", "openai_compatible", "local", "speaches", "faster-whisper-server"}
)


def build_stt(
    config: STTConfig,
    *,
    registry=None,
    run_context: Optional[RunContext] = None,
) -> STTAdapter:
    """Instantiate an STT adapter for the configured provider."""
    provider = config.provider.lower()
    if provider in ("mock", "test"):
        from nexus.realtime.adapters.stt.mock import MockSTT

        return MockSTT(config)
    if provider in _NEXUS_SERVER:
        from nexus.realtime.adapters.stt.grpc import GrpcSTT

        return GrpcSTT(config, registry=registry, run_context=run_context)
    if provider in _OPENAI_COMPATIBLE_STT:
        from nexus.realtime.adapters.stt.openai import OpenAISTT

        return OpenAISTT(config)
    if provider == "deepgram":
        from nexus.realtime.adapters.stt.deepgram import DeepgramSTT

        return DeepgramSTT(config)
    raise ValueError(f"Unknown STT provider: {config.provider!r}")


# Provider names that all speak the OpenAI /v1/audio/speech API. Point
# `base_url` at any local server (Kokoro-FastAPI, speaches, openedai-speech, ...)
# for a fully self-hosted, BYOM, offline-first setup — no paid API required.
_OPENAI_COMPATIBLE_TTS = frozenset(
    {"openai", "openai_compatible", "local", "kokoro", "speaches", "openedai-speech", "piper"}
)


def build_tts(
    config: TTSConfig,
    *,
    registry=None,
    run_context: Optional[RunContext] = None,
) -> TTSAdapter:
    """Instantiate a TTS adapter for the configured provider."""
    provider = config.provider.lower()
    if provider in ("mock", "test"):
        from nexus.realtime.adapters.tts.mock import MockTTS

        return MockTTS(config)
    if provider in _NEXUS_SERVER:
        from nexus.realtime.adapters.tts.grpc import GrpcTTS

        return GrpcTTS(config, registry=registry, run_context=run_context)
    if provider in _OPENAI_COMPATIBLE_TTS:
        from nexus.realtime.adapters.tts.openai import OpenAITTS

        return OpenAITTS(config)
    raise ValueError(f"Unknown TTS provider: {config.provider!r}")


def build_vad(
    config: VADConfig,
    *,
    registry=None,
    run_context: Optional[RunContext] = None,
) -> VADAdapter:
    """Instantiate a VAD adapter for the configured provider."""
    provider = config.provider.lower()
    if provider in ("energy", "mock", "test"):
        from nexus.realtime.adapters.vad.energy import EnergyVAD

        return EnergyVAD(config)
    if provider in _NEXUS_SERVER:
        from nexus.realtime.adapters.vad.grpc import GrpcVAD

        return GrpcVAD(config, registry=registry, run_context=run_context)
    if provider == "silero":
        try:
            from nexus.realtime.adapters.vad.silero import SileroVAD
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "Silero VAD requires extra dependencies; install torch/silero-vad."
            ) from exc
        return SileroVAD(config)
    raise ValueError(f"Unknown VAD provider: {config.provider!r}")


def build_lid(
    config: LIDConfig,
    *,
    registry=None,
    run_context: Optional[RunContext] = None,
):
    """Instantiate a LID adapter for the configured provider."""
    provider = config.provider.lower()
    if provider in ("mock", "test"):
        from nexus.realtime.adapters.lid.mock import MockLID

        return MockLID(config)
    if provider in _NEXUS_SERVER:
        from nexus.realtime.adapters.lid.grpc import GrpcLID

        return GrpcLID(config, registry=registry, run_context=run_context)
    raise ValueError(f"Unknown LID provider: {config.provider!r}")
