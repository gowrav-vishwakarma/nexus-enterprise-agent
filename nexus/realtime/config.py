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
InitialResponseMode = Literal["none", "proactive", "ivr"]


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
    speed: float = Field(
        default=1.0,
        description="Speaking rate multiplier (1.0 = normal). Engines that support it "
        "apply natively; others time-stretch the PCM (e.g. Parler).",
    )
    api_key: SecretStr = Field(default=SecretStr(""), description="Provider API key")
    base_url: Optional[str] = Field(default=None, description="Custom endpoint override (host:port or URL)")
    server_ref: Optional[str] = Field(default=None, description="Logical name in servers: config")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Engine-specific options passed through as-is (like LLM default_params)",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Deprecated alias of params — merged with params (params wins on conflict)",
    )

    def get_api_key(self) -> str:
        """Return the raw API key string."""
        return self.api_key.get_secret_value()

    def effective_params(self) -> dict[str, Any]:
        """Merged engine kwargs: ``extra`` then ``params`` (params wins)."""
        return {**self.extra, **self.params}


class LanguageConfig(BaseModel):
    """Languages this voice agent may use end-to-end (STT, reply, TTS)."""

    allowed: list[str] = Field(
        ...,
        min_length=1,
        description="ISO language codes the agent may use for STT, reply, and TTS",
    )
    default: Optional[str] = Field(
        default=None,
        description="Fallback when LID is off or detection is out-of-allowed",
    )


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
    threshold: float = Field(
        default=0.02,
        description="Energy/probability threshold — louder than this counts as speech "
        "(higher = ignore more noise / quieter barge-ins)",
    )
    silence_ms: int = Field(
        default=700,
        description="Trailing silence (ms) after speech before the assistant takes its turn",
    )
    min_speech_ms: int = Field(
        default=200,
        description="Minimum continuous speech (ms) to accept as a user turn (filters blips)",
    )
    barge_in_min_speech_ms: int = Field(
        default=250,
        description="While the assistant is speaking, how long the user must keep talking "
        "(ms) before barge-in cancels TTS/LLM (0 = interrupt on first speech frame)",
    )
    sample_rate: int = Field(default=16000, description="Audio sample rate (Hz)")
    base_url: Optional[str] = Field(default=None, description="gRPC endpoint host:port")
    server_ref: Optional[str] = Field(default=None, description="Logical name in servers: config")
    extra: dict[str, Any] = Field(default_factory=dict, description="Provider-specific options")


class InitialResponseConfig(BaseModel):
    """Greeting or IVR opening spoken when a voice session connects."""

    mode: InitialResponseMode = Field(
        default="none",
        description="none, proactive (greeting), or ivr (menu/script at connect)",
    )
    text: Optional[str] = Field(
        default=None,
        description="Fixed greeting text for proactive direct TTS or single-line IVR script",
    )
    via_llm: bool = Field(
        default=False,
        description="When true, run an LLM turn with llm_trigger before listening",
    )
    llm_trigger: Optional[str] = Field(
        default=None,
        description="Hidden user message for the connect-time LLM turn",
    )
    ivr_script: Optional[list[str]] = Field(
        default=None,
        description="Ordered lines to speak in IVR mode when via_llm is false",
    )
    emit_transcript: bool = Field(
        default=False,
        description="Whether the connect trigger appears as a user transcript event",
    )
    reply_language: Optional[str] = Field(
        default=None,
        description="TTS language for the connect greeting (defaults to languages.default)",
    )


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
    languages: Optional[LanguageConfig] = Field(
        default=None,
        description="Allowed/default language codes for this voice agent",
    )
    initial_response: Optional[InitialResponseConfig] = Field(
        default=None,
        description="Connect-time greeting or IVR opening (before first user speech)",
    )
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

    def effective_languages(self) -> LanguageConfig:
        """Resolved allowed/default languages (explicit block or backward-compatible defaults)."""
        from nexus.realtime.languages import DEFAULT_LANGUAGE, LANGUAGES

        stt_lang = (self.effective_stt().language or DEFAULT_LANGUAGE).lower().split("-")[0]
        lid = self.effective_lid()
        lid_fallback = (
            lid.fallback_language.lower().split("-")[0] if lid else stt_lang
        )

        if self.languages is not None:
            default = self.languages.default or stt_lang or DEFAULT_LANGUAGE
            return LanguageConfig(allowed=list(self.languages.allowed), default=default)

        allowed = set(LANGUAGES.keys())
        allowed.add(stt_lang)
        allowed.add(lid_fallback)
        return LanguageConfig(allowed=sorted(allowed), default=lid_fallback or stt_lang)

    def effective_initial_response(self) -> InitialResponseConfig:
        """Connect-time greeting/IVR config, defaulting to disabled."""
        return self.initial_response or InitialResponseConfig()

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
