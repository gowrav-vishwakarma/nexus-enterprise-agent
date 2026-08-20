"""Orchestration runtime wiring for AgentRunner / AgentOrchestrator."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional, Union

from nexus.config.agent import AgentConfig, AgentGroupConfig
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.multiagent.results import AgentGroupResult
from nexus.orchestration.imports import import_from_path
from nexus.orchestration.manifest import OrchestrationManifest
from nexus.orchestration.resolver import ManifestResolver
from nexus.persistence.factory import PersistenceFactory
from nexus.persistence.resolver import PersistenceResolver
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

Executor = Union[AgentRunner, AgentOrchestrator]
RunResult = Union[AgentRunResult, AgentGroupResult]


class OrchestrationRuntime:
    """Per-request wired executor built from an orchestration manifest."""

    def __init__(
        self,
        manifest: OrchestrationManifest,
        *,
        run_context: RunContext,
        tool_registry: Optional[ToolRegistry] = None,
        persistence_resolver: Optional[PersistenceResolver] = None,
        event_emitter: Optional[Any] = None,
        cross_session_enabled: bool = True,
    ) -> None:
        self.manifest = manifest
        self.run_context = run_context
        self.event_emitter = event_emitter

        self._tool_registry = _build_tool_registry(manifest, tool_registry)
        self._persistence_bundle = _build_persistence_bundle(
            manifest,
            run_context,
            persistence_resolver,
            cross_session_enabled=cross_session_enabled,
        )

        resolver = ManifestResolver(
            manifest.schema,
            manifest.prompts,
            run_context,
        )
        self._root_config = resolver.resolve_root()
        self._executor = _build_executor(
            self._root_config,
            tool_registry=self._tool_registry,
            storage_config=self._persistence_bundle.session_manager,
            run_context=run_context,
            cross_session_memory_store=self._persistence_bundle.cross_session_memory_store,
            event_emitter=event_emitter,
        )

    @classmethod
    def from_manifest(
        cls,
        manifest: OrchestrationManifest,
        *,
        run_context: RunContext,
        tool_registry: Optional[ToolRegistry] = None,
        persistence_resolver: Optional[PersistenceResolver] = None,
        event_emitter: Optional[Any] = None,
        cross_session_enabled: bool = True,
    ) -> OrchestrationRuntime:
        """Construct a runtime from a loaded manifest."""
        return cls(
            manifest,
            run_context=run_context,
            tool_registry=tool_registry,
            persistence_resolver=persistence_resolver,
            event_emitter=event_emitter,
            cross_session_enabled=cross_session_enabled,
        )

    @property
    def executor(self) -> Executor:
        return self._executor

    @property
    def root_config(self) -> Union[AgentConfig, AgentGroupConfig]:
        return self._root_config

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    async def run(
        self,
        user_message: str,
        *,
        session_id: Optional[str] = None,
        stream: Optional[bool] = None,
    ) -> RunResult:
        if isinstance(self._executor, AgentOrchestrator):
            return await self._executor.run(
                user_message,
                session_id=session_id,
                stream=stream,
            )
        return await self._executor.run(
            user_message,
            session_id=session_id,
            stream=stream,
        )

    async def run_stream(
        self,
        user_message: str,
        *,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        if isinstance(self._executor, AgentOrchestrator):
            async for event in self._executor.run_stream(
                user_message,
                session_id=session_id,
            ):
                yield event
            return
        async for event in self._executor.run_stream(
            user_message,
            session_id=session_id,
        ):
            yield event


def _build_tool_registry(
    manifest: OrchestrationManifest,
    tool_registry: Optional[ToolRegistry],
) -> ToolRegistry:
    registry = tool_registry or ToolRegistry()
    for plugin_name, import_path in manifest.plugins.items():
        plugin_cls = import_from_path(import_path)
        plugin = plugin_cls() if callable(plugin_cls) else plugin_cls
        registry.register_plugin(plugin)
        if plugin_name not in getattr(plugin, "name", plugin_name):
            # Registration uses decorator name; manifest key is documentation only.
            pass
    return registry


def _build_persistence_bundle(
    manifest: OrchestrationManifest,
    run_context: RunContext,
    persistence_resolver: Optional[PersistenceResolver],
    *,
    cross_session_enabled: bool,
):
    if persistence_resolver is not None:
        return PersistenceFactory.from_resolver(
            persistence_resolver,
            run_context.tenant_id,
            run_context.user_id,
            cross_session_enabled=cross_session_enabled,
        )
    return PersistenceFactory.from_storage_config(
        manifest.storage_config,
        cross_session_enabled=cross_session_enabled,
    )


def _build_executor(
    root_config: Union[AgentConfig, AgentGroupConfig],
    *,
    tool_registry: ToolRegistry,
    storage_config: Any,
    run_context: RunContext,
    cross_session_memory_store: Any,
    event_emitter: Optional[Any],
) -> Executor:
    if isinstance(root_config, AgentGroupConfig):
        return AgentOrchestrator(
            config=root_config,
            tool_registry=tool_registry,
            storage_config=storage_config,
            run_context=run_context,
            cross_session_memory_store=cross_session_memory_store,
            event_emitter=event_emitter,
        )
    return AgentRunner(
        config=root_config,
        tool_registry=tool_registry,
        storage_config=storage_config,
        run_context=run_context,
        event_emitter=event_emitter,
        cross_session_memory_store=cross_session_memory_store,
    )
