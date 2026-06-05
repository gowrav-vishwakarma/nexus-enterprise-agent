"""Base speech-to-speech adapter with a tool bridge.

A speech-to-speech model (e.g. OpenAI Realtime) processes audio in and audio out
directly. Nexus bridges tools by exposing the agent's tool schemas to the model
and executing tool calls through a ``tool_executor`` callback (wired to the
``ToolRegistry``), so voice agents keep the same tools as text agents.
"""

from __future__ import annotations

import abc
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from nexus.realtime.config import S2SConfig
from nexus.realtime.events import RealtimeStreamEvent

ToolExecutor = Callable[[str, dict], Awaitable[str]]


class SpeechToSpeechAdapter(abc.ABC):
    """Drive a duplex speech-to-speech model with bridged tools."""

    def __init__(
        self,
        config: S2SConfig,
        *,
        instructions: Optional[str] = None,
        tool_schemas: Optional[list[dict[str, Any]]] = None,
        tool_executor: Optional[ToolExecutor] = None,
    ) -> None:
        self.config = config
        self.instructions = instructions or config.instructions
        self.tool_schemas = tool_schemas or []
        self.tool_executor = tool_executor

    @abc.abstractmethod
    def run_audio(
        self, audio_in: AsyncIterator[bytes]
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Stream audio into the model and yield audio/text/tool events."""

    @abc.abstractmethod
    def run_text(self, text: str) -> AsyncIterator[RealtimeStreamEvent]:
        """Send a text turn into the model and yield events."""

    async def _execute_tool(self, name: str, args: dict) -> str:
        """Run a bridged tool call, returning its string result."""
        if not self.tool_executor:
            return f"[no tool executor configured for {name}]"
        return await self.tool_executor(name, args)
