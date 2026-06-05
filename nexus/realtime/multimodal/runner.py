"""Vision agent runner: a thin wrapper around AgentRunner for image input.

It accepts a :class:`~nexus.realtime.input.UserInput` (which may carry images),
swaps in a :class:`VisionContextBuilder`, and delegates to the unchanged
``AgentRunner``. Text-only inputs behave exactly like the normal runner.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional, Union

from nexus.config.agent import AgentConfig
from nexus.config.storage import SessionStorageConfig
from nexus.realtime.input import UserInput
from nexus.realtime.multimodal.context_builder import VisionContextBuilder
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry


class VisionAgentRunner:
    """Run an agent with optional image input using a vision context builder."""

    def __init__(
        self,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        storage_config: Optional[Union[SessionStorageConfig, SessionManager]] = None,
        run_context: Optional[RunContext] = None,
        event_emitter: Optional[Any] = None,
        cross_session_memory_store: Optional[Any] = None,
    ) -> None:
        self.runner = AgentRunner(
            config=config,
            tool_registry=tool_registry,
            storage_config=storage_config,
            run_context=run_context,
            event_emitter=event_emitter,
            cross_session_memory_store=cross_session_memory_store,
        )
        # Replace the default builder with a vision-aware one.
        self._vision_builder = VisionContextBuilder(event_emitter=self.runner.event_emitter)
        self.runner.ctx_builder = self._vision_builder

    @property
    def config(self) -> AgentConfig:
        """The underlying agent config."""
        return self.runner.config

    def _prime(self, user_input: UserInput) -> str:
        """Stage image parts on the builder; return the text to send."""
        self._vision_builder.pending_content_parts = user_input.image_parts()
        return user_input.to_text()

    async def run(
        self,
        user_input: Union[UserInput, str],
        session_id: Optional[str] = None,
        initial_context: Optional[dict[str, Any]] = None,
        stream: Optional[bool] = None,
    ) -> AgentRunResult:
        """Run blocking with multimodal input."""
        if isinstance(user_input, str):
            user_input = UserInput.from_text(user_input)
        text = self._prime(user_input)
        return await self.runner.run(
            text,
            session_id=session_id,
            initial_context=initial_context,
            stream=stream,
        )

    async def run_stream(
        self,
        user_input: Union[UserInput, str],
        session_id: Optional[str] = None,
        stream: Optional[bool] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Run streaming with multimodal input."""
        if isinstance(user_input, str):
            user_input = UserInput.from_text(user_input)
        text = self._prime(user_input)
        async for event in self.runner.run_stream(
            text, session_id=session_id, stream=stream
        ):
            yield event
