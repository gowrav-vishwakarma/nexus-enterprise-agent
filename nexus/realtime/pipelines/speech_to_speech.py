"""Speech-to-speech pipeline: drive a realtime model with bridged Nexus tools.

Unlike the cascaded pipeline (separate STT/LLM/TTS), this uses a single duplex
model. It still reuses the agent's persona (as instructions) and tools (bridged
to the model's function calling), and mirrors the cascaded pipeline interface
(``process_text`` / ``process_audio_stream``) so sessions/transports are shared.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from nexus.realtime.adapters.s2s.base import SpeechToSpeechAdapter
from nexus.realtime.config import RealtimeAgentConfig
from nexus.realtime.events import RealtimeStreamEvent
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SpeechToSpeechPipeline:
    """Run a voice agent on a single speech-to-speech model."""

    def __init__(
        self,
        config: RealtimeAgentConfig,
        tool_registry: Optional[ToolRegistry] = None,
        storage_config: Optional[Any] = None,
        run_context: Optional[RunContext] = None,
        cross_session_memory_store: Optional[Any] = None,
        event_emitter: Optional[Any] = None,
        *,
        adapter: Optional[SpeechToSpeechAdapter] = None,
    ) -> None:
        self.config = config
        self.duplex = config.duplex
        self.tool_registry = tool_registry or ToolRegistry()
        self.run_context = run_context or RunContext()
        self.storage_config = storage_config

        self._name_map: dict[str, tuple[str, str]] = {}
        tool_schemas = self._build_tool_schemas()
        self.adapter = adapter or self._build_adapter(tool_schemas)

    def _instructions(self) -> str:
        """Compose model instructions from the agent persona (or S2S override)."""
        s2s = self.config.effective_s2s()
        if s2s.instructions:
            return s2s.instructions
        persona = self.config.agent.persona
        if persona.system_prompt:
            return persona.system_prompt
        parts = [f"You are {persona.role}.", f"Goal: {persona.goal}"]
        if persona.backstory:
            parts.append(persona.backstory)
        return " ".join(parts)

    def _build_tool_schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas with realtime-safe names and a name map."""
        raw = self.tool_registry.get_tool_schemas_for_llm(
            plugin_names=self.config.agent.tool_plugins or None
        )
        schemas: list[dict[str, Any]] = []
        for schema in raw:
            plugin, _, tool = schema["name"].partition(".")
            safe = schema["name"].replace(".", "-")
            self._name_map[safe] = (plugin, tool)
            schemas.append({**schema, "name": safe})
        return schemas

    async def _tool_executor(self, name: str, args: dict) -> str:
        """Execute a bridged tool call by its realtime-safe name."""
        plugin, tool = self._name_map.get(name, (name, ""))
        # RCS-injected control field is not used in S2S turns.
        args = {k: v for k, v in args.items() if k != "_context_updates"}
        try:
            result = await self.tool_registry.execute(plugin, tool, args, self.run_context)
        except Exception as exc:  # pragma: no cover - tool error surfaced to model
            logger.error("S2S tool %s.%s failed: %s", plugin, tool, exc)
            return f"Error: {exc}"
        return result if isinstance(result, str) else str(result)

    def _build_adapter(self, tool_schemas: list[dict[str, Any]]) -> SpeechToSpeechAdapter:
        """Instantiate the S2S adapter for the configured provider."""
        s2s = self.config.effective_s2s()
        provider = s2s.provider.lower()
        kwargs = dict(
            instructions=self._instructions(),
            tool_schemas=tool_schemas,
            tool_executor=self._tool_executor,
        )
        if provider in ("mock", "test"):
            from nexus.realtime.adapters.s2s.mock import MockS2S

            return MockS2S(s2s, **kwargs)
        if provider in ("openai", "openai_realtime"):
            from nexus.realtime.adapters.s2s.openai_realtime import OpenAIRealtimeS2S

            return OpenAIRealtimeS2S(s2s, **kwargs)
        raise ValueError(f"Unknown S2S provider: {s2s.provider!r}")

    async def process_text(
        self,
        text: str,
        session_id: Optional[str] = None,
        *,
        emit_transcript: bool = True,
        **_: Any,
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Process a single text turn through the S2S model."""
        async for event in self.adapter.run_text(text):
            # The model emits its own input transcript; drop it if not wanted.
            if not emit_transcript and event.event_type == "transcript_final":
                continue
            yield event

    async def process_utterance(
        self, audio: bytes, session_id: Optional[str] = None, **_: Any
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Process one audio blob through the S2S model."""

        async def _single() -> AsyncIterator[bytes]:
            yield audio

        async for event in self.adapter.run_audio(_single()):
            yield event

    async def process_audio_stream(
        self, audio_in: AsyncIterator[bytes], session_id: Optional[str] = None
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Stream continuous audio through the duplex S2S model."""
        yield RealtimeStreamEvent(event_type="session_started", data={"duplex": self.duplex, "modality": "voice_s2s"})
        async for event in self.adapter.run_audio(audio_in):
            yield event
