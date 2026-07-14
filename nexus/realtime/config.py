"""Configuration models for realtime (voice/AV) agents.

These wrap the unchanged :class:`~nexus.config.agent.AgentConfig` with the extra
knobs a voice agent needs (STT, TTS, VAD, S2S, duplex mode). A realtime agent is
"just an AgentConfig plus a modality", so all existing config (persona, llm,
tools, rcs, memory) is reused as-is.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, SecretStr

from nexus.config.agent import AgentConfig

Modality = Literal["text", "vision_text", "voice_cascaded", "voice_s2s"]
DuplexMode = Literal["half", "full"]


class STTConfig(BaseModel):
    """Speech-to-text adapter configuration."""

    provider: str = Field(default="mock", description="STT provider, e.g. deepgram, openai, mock, nexus_server")
    model: Optional[str] = Field(default=None, description="Provider model, e.g. nova-3")
    language: str = Field(default="en", description="Primary language code")
    sample_rate: int = Field(default=16000, description="Input audio sample rate (Hz)")
    interim_results: bool = Field(default=True, description="Emit partial transcripts")
    api_key: SecretStr = Field(default=SecretStr(""), description="Provider API key")
    base_url: Optional[str] = Field(default=None, description="Custom endpoint override (host:port or URL)")
    server_ref: Optional[str] = Field(default=None, description="Logical name in servers: config")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific options")

    def get_api_key(self) -> str:
        """Return the raw API key string."""
        return self.api_key.get_secret_value()


class TTSConfig(BaseModel):
    """Text-to-speech adapter configuration."""

    provider: str = Field(default="mock", description="TTS provider, e.g. openai, cartesia, mock, nexus_server")
    model: Optional[str] = Field(default=None, description="Provider model, e.g. tts-1")
    voice: Optional[str] = Field(default=None, description="Voice id/name")
    sample_rate: int = Field(default=24000, description="Output audio sample rate (Hz)")
    audio_format: str = Field(default="pcm16", description="Output encoding, e.g. pcm16, mp3")
    speed: float = Field(default=1.0, description="Speaking rate multiplier")
    api_key: SecretStr = Field(default=SecretStr(""), description="Provider API key")
    base_url: Optional[str] = Field(default=None, description="Custom endpoint override (host:port or URL)")
    server_ref: Optional[str] = Field(default=None, description="Logical name in servers: config")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific options")

    def get_api_key(self) -> str:
        """Return the raw API key string."""
        return self.api_key.get_secret_value()


class LIDConfig(BaseModel):
    """Language-identification adapter configuration."""

    provider: str = Field(
        default="mock", description="LID provider: mock, nexus_server"
    )
    fallback_language: str = Field(
        default="hi", description="Language when detection is low-confidence"
    )
    sample_rate: int = Field(default=16000, description="Input audio sample rate (Hz)")
    base_url: Optional[str] = Field(default=None, description="gRPC endpoint host:port")
    server_ref: Optional[str] = Field(default=None, description="Logical name in servers: config")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific options")


class VADConfig(BaseModel):
    """Voice-activity-detection / turn-detection configuration."""

    provider: str = Field(default="energy", description="VAD provider: energy, silero, nexus_server")
    threshold: float = Field(default=0.02, description="Energy/probability threshold for speech")
    silence_ms: int = Field(default=700, description="Trailing silence that ends a turn (ms)")
    min_speech_ms: int = Field(default=200, description="Minimum speech length to count as a turn (ms)")
    sample_rate: int = Field(default=16000, description="Audio sample rate (Hz)")
    base_url: Optional[str] = Field(default=None, description="gRPC endpoint host:port")
    server_ref: Optional[str] = Field(default=None, description="Logical name in servers: config")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific options")


class S2SConfig(BaseModel):
    """Speech-to-speech (realtime model) configuration."""

    provider: str = Field(default="openai_realtime", description="S2S provider")
    model: str = Field(default="gpt-realtime", description="Realtime model name")
    voice: Optional[str] = Field(default="marin", description="Output voice")
    instructions: Optional[str] = Field(default=None, description="System instructions override")
    api_key: SecretStr = Field(default=SecretStr(""), description="Provider API key")
    base_url: Optional[str] = Field(default=None, description="Custom endpoint override")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific options")

    def get_api_key(self) -> str:
        """Return the raw API key string."""
        return self.api_key.get_secret_value()


class RealtimeAgentConfig(BaseModel):
    """A voice/AV-capable agent: an AgentConfig plus a modality and media adapters."""

    name: str = Field(..., description="Unique realtime agent identifier")
    modality: Modality = Field(default="voice_cascaded", description="How this agent handles media")
    duplex: DuplexMode = Field(default="full", description="half (IVR) or full (barge-in) duplex")
    agent: AgentConfig = Field(..., description="Underlying text agent configuration (reused as-is)")
    stt: Optional[STTConfig] = Field(default=None, description="STT config (cascaded/vision voice notes)")
    tts: Optional[TTSConfig] = Field(default=None, description="TTS config (cascaded output)")
    vad: Optional[VADConfig] = Field(default=None, description="VAD/turn detection config")
    lid: Optional[LIDConfig] = Field(default=None, description="Per-turn language detection config")
    s2s: Optional[S2SConfig] = Field(default=None, description="Speech-to-speech config (voice_s2s)")

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_voice(self) -> bool:
        """True for voice modalities (cascaded or speech-to-speech)."""
        return self.modality in ("voice_cascaded", "voice_s2s")

    def effective_stt(self) -> STTConfig:
        """STT config, defaulting to a mock adapter when unset."""
        return self.stt or STTConfig()

    def effective_tts(self) -> TTSConfig:
        """TTS config, defaulting to a mock adapter when unset."""
        return self.tts or TTSConfig()

    def effective_vad(self) -> VADConfig:
        """VAD config, defaulting to the built-in energy detector when unset."""
        return self.vad or VADConfig()

    def effective_lid(self) -> Optional[LIDConfig]:
        """LID config when per-turn language detection is enabled."""
        return self.lid

    def effective_s2s(self) -> S2SConfig:
        """S2S config, defaulting to OpenAI Realtime when unset."""
        return self.s2s or S2SConfig()


class VoiceTeamConfig(BaseModel):
    """A multi-agent voice team: a responder plus optional listener and context agent.

    - ``responder``: the user-facing voice agent (required).
    - ``context_agent``: an optional text agent that runs in parallel on the
      transcript and injects extra context into the responder.
    - ``listener``: an optional dedicated transcription agent; when omitted the
      responder's own STT handles transcription.
    """

    name: str = Field(..., description="Voice team name")
    pattern: Literal["voice_team"] = Field(default="voice_team")
    duplex: DuplexMode = Field(default="full", description="half or full duplex for the team")
    responder: RealtimeAgentConfig = Field(..., description="User-facing voice agent")
    context_agent: Optional[AgentConfig] = Field(
        default=None, description="Parallel text agent that supplies live context"
    )
    listener: Optional[RealtimeAgentConfig] = Field(
        default=None, description="Optional dedicated transcription agent"
    )
    context_injection_var: str = Field(
        default="live_context",
        description="Jinja/initial_context key the responder receives context under",
    )

    model_config = {"arbitrary_types_allowed": True}
