"""Realtime runtime: build voice pipelines from an orchestration manifest.

Mirrors :class:`~nexus.orchestration.runtime.OrchestrationRuntime` but produces
voice pipelines (cascaded or speech-to-speech) and voice teams. A realtime agent
in the manifest looks like a normal agent with extra ``modality``/``stt``/``tts``/
``vad``/``s2s``/``duplex`` keys and its text config under an ``agent:`` block.
"""

from __future__ import annotations

from typing import Any, Optional

from nexus.orchestration.manifest import OrchestrationManifest
from nexus.orchestration.resolver import ManifestResolver
from nexus.orchestration.runtime import (
    _build_persistence_bundle,
    _build_tool_registry,
)
from nexus.persistence.factory import PersistenceBundle
from nexus.realtime.config import (
    RealtimeAgentConfig,
    S2SConfig,
    STTConfig,
    TTSConfig,
    VADConfig,
    VoiceTeamConfig,
)
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

_REALTIME_KEYS = {"modality", "duplex", "stt", "tts", "vad", "s2s"}


def resolve_realtime_agent(
    name: str,
    manifest: OrchestrationManifest,
    run_context: RunContext,
) -> RealtimeAgentConfig:
    """Resolve a manifest agent entry into a RealtimeAgentConfig."""
    schema = manifest.schema
    if name not in schema.agents:
        raise KeyError(f"Realtime agent {name!r} not found in manifest agents")
    spec = schema.agents[name]

    agent_spec = spec.get("agent")
    if agent_spec is None:
        agent_spec = {k: v for k, v in spec.items() if k not in _REALTIME_KEYS}

    resolver = ManifestResolver(schema, manifest.prompts, run_context)
    agent_config = resolver._resolve_agent(name, agent_spec)

    return RealtimeAgentConfig(
        name=name,
        modality=spec.get("modality", "voice_cascaded"),
        duplex=spec.get("duplex", "full"),
        agent=agent_config,
        stt=STTConfig(**spec["stt"]) if "stt" in spec else None,
        tts=TTSConfig(**spec["tts"]) if "tts" in spec else None,
        vad=VADConfig(**spec["vad"]) if "vad" in spec else None,
        s2s=S2SConfig(**spec["s2s"]) if "s2s" in spec else None,
    )


def resolve_voice_team(
    name: str,
    manifest: OrchestrationManifest,
    run_context: RunContext,
) -> VoiceTeamConfig:
    """Resolve a manifest group (pattern: voice_team) into a VoiceTeamConfig.

    Members are referenced by name; ``responder`` is required, ``context_agent``
    and ``listener`` are optional.
    """
    schema = manifest.schema
    if name not in schema.groups:
        raise KeyError(f"Voice team {name!r} not found in manifest groups")
    spec = schema.groups[name]
    members = spec.get("members", [])

    # Member entries may declare role: responder|context_agent|listener, else by name.
    def _find(role: str) -> Optional[str]:
        for member in members:
            if isinstance(member, dict):
                if member.get("role") == role or member.get("name") == role:
                    return member.get("name") or role
            elif isinstance(member, str) and member == role:
                return member
        return None

    responder_name = _find("responder")
    if not responder_name:
        raise ValueError(f"voice_team {name!r} requires a member named/role 'responder'")

    responder = resolve_realtime_agent(responder_name, manifest, run_context)

    context_name = _find("context_agent")
    context_agent = None
    if context_name and context_name in schema.agents:
        resolver = ManifestResolver(schema, manifest.prompts, run_context)
        c_spec = schema.agents[context_name]
        c_agent_spec = c_spec.get("agent", {k: v for k, v in c_spec.items() if k not in _REALTIME_KEYS})
        context_agent = resolver._resolve_agent(context_name, c_agent_spec)

    listener_name = _find("listener")
    listener = None
    if listener_name and listener_name in schema.agents and listener_name != responder_name:
        listener = resolve_realtime_agent(listener_name, manifest, run_context)

    return VoiceTeamConfig(
        name=name,
        duplex=spec.get("duplex", "full"),
        responder=responder,
        context_agent=context_agent,
        listener=listener,
        context_injection_var=spec.get("context_injection_var", "live_context"),
    )


class RealtimeRuntime:
    """Per-request factory that builds voice pipelines/teams from a manifest."""

    def __init__(
        self,
        manifest: OrchestrationManifest,
        *,
        run_context: RunContext,
        tool_registry: Optional[ToolRegistry] = None,
        persistence_resolver: Optional[Any] = None,
        event_emitter: Optional[Any] = None,
        cross_session_enabled: bool = True,
    ) -> None:
        self.manifest = manifest
        self.run_context = run_context
        self.event_emitter = event_emitter
        self._tool_registry = _build_tool_registry(manifest, tool_registry)
        self._persistence: PersistenceBundle = _build_persistence_bundle(
            manifest,
            run_context,
            persistence_resolver,
            cross_session_enabled=cross_session_enabled,
        )

    @classmethod
    def from_manifest(
        cls,
        manifest: OrchestrationManifest,
        *,
        run_context: RunContext,
        tool_registry: Optional[ToolRegistry] = None,
        persistence_resolver: Optional[Any] = None,
        event_emitter: Optional[Any] = None,
        cross_session_enabled: bool = True,
    ) -> "RealtimeRuntime":
        """Construct a realtime runtime from a loaded manifest."""
        return cls(
            manifest,
            run_context=run_context,
            tool_registry=tool_registry,
            persistence_resolver=persistence_resolver,
            event_emitter=event_emitter,
            cross_session_enabled=cross_session_enabled,
        )

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    def build_pipeline(self, name: Optional[str] = None):
        """Build a voice pipeline for a named realtime agent (defaults to root)."""
        agent_name = name or self.manifest.schema.root
        rt_config = resolve_realtime_agent(agent_name, self.manifest, self.run_context)
        return self._pipeline_for(rt_config)

    def _pipeline_for(self, rt_config: RealtimeAgentConfig):
        """Instantiate the pipeline matching the agent's modality."""
        if rt_config.modality == "voice_s2s":
            from nexus.realtime.pipelines.speech_to_speech import SpeechToSpeechPipeline

            return SpeechToSpeechPipeline(
                rt_config,
                tool_registry=self._tool_registry,
                storage_config=self._persistence.session_manager,
                run_context=self.run_context,
                cross_session_memory_store=self._persistence.cross_session_memory_store,
                event_emitter=self.event_emitter,
            )

        from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline

        return CascadedVoicePipeline(
            rt_config,
            tool_registry=self._tool_registry,
            storage_config=self._persistence.session_manager,
            run_context=self.run_context,
            cross_session_memory_store=self._persistence.cross_session_memory_store,
            event_emitter=self.event_emitter,
        )

    def build_voice_team(self, name: Optional[str] = None):
        """Build a multi-agent voice team for a named group (defaults to root)."""
        from nexus.realtime.patterns.voice_conversation import VoiceTeam

        group_name = name or self.manifest.schema.root
        team_config = resolve_voice_team(group_name, self.manifest, self.run_context)
        return VoiceTeam(
            team_config,
            tool_registry=self._tool_registry,
            storage_config=self._persistence.session_manager,
            run_context=self.run_context,
            cross_session_memory_store=self._persistence.cross_session_memory_store,
            event_emitter=self.event_emitter,
        )
