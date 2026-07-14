"""Realtime, voice, and multimodal agents for Nexus.

This package adds voice (cascaded STT->LLM->TTS and speech-to-speech), vision
(image input), half/full duplex, IVR, and multi-agent voice teams -- all on top
of the unchanged text :class:`~nexus.runner.agent_runner.AgentRunner`.

Heavy/optional providers (websockets, deepgram, grpc media servers, ...) are imported
lazily inside their adapters, so importing this package never requires them.
Install extras with ``pip install nexus-enterprise-agent[realtime]``.
"""

from nexus.realtime.config import (
    DuplexMode,
    Modality,
    RealtimeAgentConfig,
    S2SConfig,
    STTConfig,
    TTSConfig,
    VADConfig,
    VoiceTeamConfig,
)
from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.input import (
    AudioPart,
    ContentPart,
    ImageBase64Part,
    ImageUrlPart,
    TextPart,
    UserInput,
)
from nexus.realtime.multimodal import VisionAgentRunner, VisionContextBuilder

__all__ = [
    # Config
    "RealtimeAgentConfig",
    "VoiceTeamConfig",
    "STTConfig",
    "TTSConfig",
    "VADConfig",
    "S2SConfig",
    "Modality",
    "DuplexMode",
    # Input / events
    "UserInput",
    "ContentPart",
    "TextPart",
    "ImageUrlPart",
    "ImageBase64Part",
    "AudioPart",
    "RealtimeStreamEvent",
    # Vision
    "VisionContextBuilder",
    "VisionAgentRunner",
    # Lazily loaded (see __getattr__)
    "CascadedVoicePipeline",
    "SpeechToSpeechPipeline",
    "RealtimeSession",
    "RealtimeRuntime",
    "VoiceTeam",
]


def __getattr__(name: str):
    """Lazily expose pipeline/session/runtime classes (avoid import cost upfront)."""
    if name in ("CascadedVoicePipeline", "RealtimeSession"):
        from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
        from nexus.realtime.session import RealtimeSession

        return {"CascadedVoicePipeline": CascadedVoicePipeline, "RealtimeSession": RealtimeSession}[name]
    if name == "SpeechToSpeechPipeline":
        from nexus.realtime.pipelines.speech_to_speech import SpeechToSpeechPipeline

        return SpeechToSpeechPipeline
    if name == "RealtimeRuntime":
        from nexus.realtime.runtime import RealtimeRuntime

        return RealtimeRuntime
    if name == "VoiceTeam":
        from nexus.realtime.patterns.voice_conversation import VoiceTeam

        return VoiceTeam
    raise AttributeError(f"module 'nexus.realtime' has no attribute {name!r}")
