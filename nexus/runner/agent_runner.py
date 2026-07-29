"""Agent Runner orchestrating the main agentic loop with RCS."""

import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Union

from nexus.config.agent import AgentConfig
from nexus.config.storage import SessionStorageConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.context.summarizer import ContextSummarizer
from nexus.events.emitter import NexusEventEmitter, StdoutEventSink
from nexus.events.models import (
    AgentStartedEvent,
    AgentCompletedEvent,
    AgentErrorEvent,
    TurnStartedEvent,
    TurnCompletedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    LLMCallStartedEvent,
    LLMCallCompletedEvent,
    LLMCallErrorEvent,
    LLMStreamChunkEvent,
)
from nexus.llm.proxy import LLMProxy
from nexus.llm.content_tool_calls import build_assistant_llm_message, promote_content_tool_calls
from nexus.llm.response import LLMResponse, TokenUsage, ToolCallRequest
from nexus.llm.token_counter import TokenCounter
from nexus.memory.curator import MemoryCurator
from nexus.memory.cross_session_store import (
    CrossSessionMemoryStore,
    resolve_cross_session_namespace,
)
from nexus.rcs.compactor import ServerCompactor
from nexus.runner.hooks import TurnContext, TurnDecision
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, PendingInteraction, ToolCallRecord, TurnRecord
from nexus.skills.catalog import build_explicit_skills_block, build_skills_catalog
from nexus.skills.plugin import create_skills_plugin
from nexus.skills.registry import SkillsRegistry
from nexus.tools.context import RunContext
from nexus.tools.interceptor import ContextUpdateInterceptor
from nexus.tools.registry import ToolRegistry
from nexus.tools.toolsets import filter_schemas_by_tools

logger = logging.getLogger(__name__)


@dataclass
class _LoopState:
    """Holds the terminal result produced by _run_loop."""

    result: Optional[AgentRunResult] = None


def _merge_tool_call_delta(accumulated: dict[int, dict[str, Any]], delta: dict[str, Any]) -> None:
    """Merge an incremental tool-call chunk into accumulated state."""
    index = delta.get("index", 0)
    if index not in accumulated:
        accumulated[index] = {"id": None, "name": "", "arguments": ""}
    entry = accumulated[index]
    if delta.get("id"):
        entry["id"] = delta["id"]
    if delta.get("name"):
        entry["name"] = delta["name"]
    if delta.get("arguments"):
        entry["arguments"] += delta["arguments"] or ""
    fn = delta.get("function")
    if isinstance(fn, dict):
        if fn.get("name"):
            entry["name"] = fn["name"]
        if fn.get("arguments"):
            entry["arguments"] += fn["arguments"] or ""


def _tool_calls_from_accumulated(accumulated: dict[int, dict[str, Any]]) -> list[ToolCallRequest]:
    """Build ToolCallRequest list from merged streaming tool-call deltas."""
    tool_calls: list[ToolCallRequest] = []
    for idx in sorted(accumulated.keys()):
        tc = accumulated[idx]
        if not tc.get("name"):
            continue
        if not tc.get("id"):
            tc["id"] = f"call_stream_{idx}"
        try:
            tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
        except json.JSONDecodeError:
            tool_input = {}
        tool_calls.append(
            ToolCallRequest(
                id=tc["id"],
                tool_name=tc["name"],
                tool_input=tool_input,
            )
        )
    return tool_calls


class AgentRunner:
    """Orchestrates single-agent execution loops, handling state, tools, and RCS."""

    def __init__(
        self,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        storage_config: Optional[Union[SessionStorageConfig, SessionManager]] = None,
        run_context: Optional[RunContext] = None,
        event_emitter: Optional[NexusEventEmitter] = None,
        cross_session_memory_store: Optional[CrossSessionMemoryStore] = None,
        on_turn_end: Optional[
            Callable[[TurnContext], Awaitable[Optional[TurnDecision]]]
        ] = None,
    ):
        self.config = config
        self.tool_registry = tool_registry

        # Load or initialize Session Manager
        if isinstance(storage_config, SessionManager):
            self.session_manager = storage_config
        elif isinstance(storage_config, SessionStorageConfig):
            self.session_manager = SessionManager.from_config(storage_config)
        else:
            if self.config.storage:
                self.session_manager = SessionManager.from_config(self.config.storage)
            else:
                self.session_manager = SessionManager()

        self.run_context = run_context or RunContext()
        self.cross_session_memory_store = cross_session_memory_store
        self.on_turn_end = on_turn_end
        self._user_memory: dict[str, str] = {}

        self.event_emitter = event_emitter or NexusEventEmitter()
        if self.config.trace_enabled and not self.event_emitter._sinks:
            if self.config.trace_sink == "stdout":
                self.event_emitter.register_sink(StdoutEventSink())
            elif self.config.trace_sink == "otel":
                from nexus.events.emitter import OTelEventSink
                self.event_emitter.register_sink(OTelEventSink())

        self.llm_proxy = LLMProxy(self.config.llm)
        self.ctx_builder = ContextWindowBuilder(event_emitter=self.event_emitter)
        self.interceptor = ContextUpdateInterceptor(event_emitter=self.event_emitter)
        self.compactor = ServerCompactor(
            config=self.config.rcs.fallback_compactor,
            llm_proxy=self.llm_proxy,
            storage_adapter=self.session_manager,
            event_emitter=self.event_emitter,
        )

        self.memory_curator = MemoryCurator(
            config=self.config.memory,
            llm_proxy=self.llm_proxy,
            session_manager=self.session_manager,
            tool_registry=self.tool_registry,
            run_context=self.run_context,
            event_emitter=self.event_emitter,
            cross_session_memory_store=self.cross_session_memory_store,
            agent_name=self.config.name,
        )
        self.context_summarizer = ContextSummarizer(
            config=self.config.context_summary,
            llm_proxy=self.llm_proxy,
            session_manager=self.session_manager,
            event_emitter=self.event_emitter,
        )

        self.skills_registry: Optional[SkillsRegistry] = None
        self._skills_catalog: Optional[str] = None
        self._explicit_skills_content: Optional[str] = None
        self._skill_store = None
        self._skill_scope_resolver = None
        self._allowed_tools: Optional[set[str]] = None
        self._runtime_granted_tools: set[str] = set()
        if self.config.skills.enabled:
            self.skills_registry = SkillsRegistry(self.config.skills)

    def _resolve_stream(self, stream: Optional[bool]) -> bool:
        """Resolve effective streaming mode from per-call override or config default."""
        return self.config.stream_output if stream is None else stream

    def _session_scope(
        self, session: Optional[AgentSession] = None
    ):
        """Build a SessionScope from run context (and session fallback)."""
        from nexus.session.scope import SessionScope

        return SessionScope(
            tenant_id=self.run_context.tenant_id
            or (session.tenant_id if session else None),
            company_id=self.run_context.company_id
            or (session.company_id if session else None),
            user_id=self.run_context.user_id
            or (session.user_id if session else None),
        )

    async def _persist_turn(
        self, session: AgentSession, turn: TurnRecord
    ) -> AgentSession:
        """Append a turn and reload. Skips storage when run is non-persistable."""
        if not self.run_context.should_persist:
            session.turns.append(turn)
            session.update_timestamp()
            return session
        await self.session_manager.append_turn(
            session.session_id,
            turn,
            scope=self._session_scope(session),
        )
        reloaded = await self.session_manager.load_session(
            session.session_id, scope=self._session_scope(session)
        )
        return reloaded if reloaded is not None else session

    async def _maybe_save_session(self, session: AgentSession) -> None:
        """Save session unless the run is non-persistable."""
        if not self.run_context.should_persist:
            return
        await self.session_manager.save_session(session)

    def _json_safe_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON-serializable copy of state; skip bad values."""
        safe: dict[str, Any] = {}
        for key, value in state.items():
            try:
                json.dumps(value)
                safe[key] = value
            except (TypeError, ValueError):
                logger.warning("AgentRunner: skipping non-serializable state key %r", key)
        return safe

    def _hydrate_state_from_session(
        self,
        session: AgentSession,
        initial_context: Optional[dict[str, Any]],
    ) -> None:
        """Load checkpoint state: session base, initial_context overlay, pre-set ctx wins."""
        base = dict(session.state or {})
        if initial_context:
            base.update(initial_context)
        pre_set = dict(self.run_context.state)
        merged = {**base, **pre_set}
        self.run_context.state = merged
        session.state = dict(merged)

    async def _persist_turn_with_state(
        self, session: AgentSession, turn: TurnRecord
    ) -> AgentSession:
        """Sync durable state to session, save, append turn, re-apply state snapshot."""
        snapshot = self._json_safe_state(dict(self.run_context.state))
        session.state = snapshot
        self.run_context.state = dict(snapshot)
        await self._maybe_save_session(session)
        session = await self._persist_turn(session, turn)
        session.state = dict(snapshot)
        self.run_context.state = dict(snapshot)
        return session

    async def _invoke_turn_end_hook(
        self,
        session: AgentSession,
        session_turn_index: int,
        run_turn_index: int,
        tool_results: list[dict[str, Any]],
        final_response: Optional[str],
    ) -> Optional[TurnDecision]:
        if not self.on_turn_end:
            return None
        ctx = TurnContext(
            session=session,
            turn_index=session_turn_index,
            run_turn_index=run_turn_index,
            tool_results=tool_results,
            state=self.run_context.state,
            final_response=final_response,
        )
        try:
            return await self.on_turn_end(ctx)
        except Exception as exc:
            logger.warning("AgentRunner: on_turn_end hook failed: %s", exc)
            return None

    def _maybe_pause_for_human_in_loop(
        self, session: AgentSession, run_turn_index: int
    ) -> bool:
        """Return True if the run should pause for configured human-in-the-loop."""
        limit = self.config.turns.human_in_loop_after_turns
        if limit is None:
            return False
        if run_turn_index + 1 < limit:
            return False
        session.pending_interactions.append(
            PendingInteraction(
                tc_id="HITL",
                call_id="",
                tool_name="human_in_loop",
                args={},
                kind="elicitation",
            )
        )
        return True

    def _effective_tool_plugins(self) -> list[str]:
        """Return tool plugin allow-list, auto-including skills/memory when enabled."""
        plugins = list(self.config.tool_plugins)
        if self.config.skills.enabled and "skills" not in plugins:
            plugins.append("skills")
        if (
            self.config.memory.enabled
            and self.config.memory.expose_tools
            and "memory" not in plugins
        ):
            plugins.append("memory")
        if (
            self.config.skills.enabled
            and self.config.skills.expose_manage_tools
            and "skill_manage" not in plugins
        ):
            plugins.append("skill_manage")
        return plugins

    def _setup_skills(self) -> None:
        """Register skills/memory plugins and prepare prompt injection content."""
        self._setup_memory_plugin()
        self._setup_learned_skills()

        if not self.skills_registry:
            return

        plugin = create_skills_plugin(
            self.skills_registry,
            self.config.skills,
            self.run_context,
        )
        self.tool_registry.register_plugin(plugin)

        mode = self.config.skills.activation_mode
        self._skills_catalog = None
        self._explicit_skills_content = None

        if mode in ("auto", "both"):
            skills = self.skills_registry.list_skills(self.run_context)
            self._skills_catalog = build_skills_catalog(skills)

        if mode in ("explicit", "both"):
            explicit = self.skills_registry.resolve_explicit_skills(self.run_context)
            self._explicit_skills_content = build_explicit_skills_block(explicit)

    def _setup_memory_plugin(self) -> None:
        if not (
            self.config.memory.enabled
            and self.config.memory.expose_tools
            and self.cross_session_memory_store
        ):
            return
        from nexus.memory.plugin import create_memory_plugin

        plugin = create_memory_plugin(
            self.cross_session_memory_store,
            self.config.memory,
            agent_name=self.config.name,
        )
        self.tool_registry.register_plugin(plugin)

    def _setup_learned_skills(self) -> None:
        cfg = self.config.skills
        if not cfg.enabled or cfg.store_backend == "none":
            self._skill_store = None
            return
        from nexus.skills.scope import build_skill_scope_resolver
        from nexus.skills.store import FileSkillStore, InMemorySkillStore

        self._skill_scope_resolver = build_skill_scope_resolver(cfg.scope)
        if cfg.store_backend == "memory":
            self._skill_store = InMemorySkillStore()
        elif cfg.store_backend == "file":
            root = cfg.store_config.get("root", "./learned_skills")
            self._skill_store = FileSkillStore(root, scope_keys=list(cfg.scope.keys))
        elif cfg.store_backend == "custom" and cfg.store_class:
            from importlib import import_module

            module_path, _, name = cfg.store_class.rpartition(".")
            cls = getattr(import_module(module_path), name)
            self._skill_store = cls(**cfg.store_config)
        else:
            self._skill_store = None
            return
        if cfg.expose_manage_tools:
            from nexus.skills.manage_plugin import create_skill_manage_plugin

            self.tool_registry.register_plugin(
                create_skill_manage_plugin(self._skill_store, self._skill_scope_resolver)
            )

    def _filter_tool_schemas(self, tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply toolset allow-list and hide run_skill_script unless enabled."""
        schemas = filter_schemas_by_tools(tool_schemas, self._allowed_tools)
        if not self.skills_registry:
            return schemas
        expose_scripts = (
            self.config.skills.allow_scripts
            and self.skills_registry.has_scripts(self.run_context)
        )
        if expose_scripts:
            return schemas
        return [s for s in schemas if s.get("name") != "skills.run_skill_script"]

    def _resolve_toolsets(self) -> None:
        """Compute the allowed tool names from the agent's ``toolset``.

        A per-run ``toolset_override`` in the run context takes precedence over
        ``config.toolset``. When neither is set the allow-list is ``None`` (no
        restriction — all registered tools are visible).
        """
        override = self.run_context.get("toolset_override")
        toolset = override if override is not None else self.config.toolset
        self._allowed_tools = self.tool_registry.resolve_toolset(toolset)
        if self._allowed_tools is not None and self._runtime_granted_tools:
            self._allowed_tools |= self._runtime_granted_tools

    def grant_tools(self, names: Union[str, list[str]]) -> None:
        """Add explicit tool names to this agent's allow-list at runtime.

        Takes effect on the next turn (schemas are re-filtered each turn). When
        the agent has no toolset restriction (``_allowed_tools is None``) every
        registered tool is already visible, so this is a no-op for the allow-list
        (grants are still remembered for when a toolset restriction applies).
        """
        if isinstance(names, str):
            names = [names]
        granted = set(names)
        self._runtime_granted_tools |= granted
        if self._allowed_tools is None:
            return
        self._allowed_tools |= granted

    def grant_toolset(self, name_or_names: Union[str, list[str]]) -> None:
        """Resolve a toolset (or names) via the registry and union it in.

        No-op when the agent has no toolset restriction (all tools visible).
        """
        if self._allowed_tools is None:
            return
        resolved = self.tool_registry.resolve_toolset(name_or_names)
        if resolved:
            self._allowed_tools |= resolved

    def revoke_tools(self, names: Union[str, list[str]]) -> None:
        """Remove tool names from this agent's allow-list at runtime."""
        if self._allowed_tools is None:
            return
        if isinstance(names, str):
            names = [names]
        self._allowed_tools -= set(names)

    async def _inject_learned_skills(self, user_message: str) -> None:
        """Append relevant learned skills into explicit skills content."""
        if not (
            self._skill_store
            and self.config.skills.inject_learned
            and self._skill_scope_resolver
        ):
            return
        from nexus.skills.store import build_learned_skills_block

        scope = self._skill_scope_resolver.resolve(self.run_context)
        skills = await self._skill_store.search(
            scope, user_message, k=self.config.skills.retrieval_k
        )
        block = build_learned_skills_block(skills)
        if not block:
            return
        if self._explicit_skills_content:
            self._explicit_skills_content = self._explicit_skills_content + "\n\n" + block
        else:
            self._explicit_skills_content = block

    def _memory_store_namespace(self, store_name: str = "") -> str:
        """Resolve namespace for a named store (same rule as MemoryPlugin)."""
        base = resolve_cross_session_namespace(
            self.config.memory.namespace, self.config.name
        )
        if store_name and store_name != "default":
            return f"{base}:{store_name}"
        return base

    @staticmethod
    def _trim_to_char_budget(
        entries: dict[str, str], char_budget: int
    ) -> dict[str, str]:
        """Soft-trim entries for prompt inject only (oldest keys dropped first)."""
        if char_budget <= 0 or not entries:
            return entries
        kept: dict[str, str] = {}
        used = 0
        # Prefer keeping the most recently ordered items (dict insertion order).
        for key, value in reversed(list(entries.items())):
            line_len = len(f"{key}: {value}") + (1 if kept else 0)
            if used + line_len > char_budget:
                continue
            kept[key] = value
            used += line_len
        # Restore original relative order among kept keys.
        return {k: entries[k] for k in entries if k in kept}

    async def _load_user_memory(self) -> dict[str, str]:
        """Load cross-session user facts for injection into the system prompt.

        When ``memory.stores`` is configured, loads every store with
        ``inject="always"`` using the same namespace suffix rule as the memory
        plugin. Multiple stores prefix keys as ``{store}/{key}``.
        """
        if not self.config.memory.enabled or not self.cross_session_memory_store:
            return {}
        if not self.run_context.user_id:
            return {}

        company_id = self.run_context.company_id
        stores = list(self.config.memory.stores)
        try:
            if not stores:
                namespace = self._memory_store_namespace("default")
                record = await self.cross_session_memory_store.load(
                    self.run_context.tenant_id,
                    self.run_context.user_id,
                    namespace,
                    company_id=company_id,
                )
                if record and record.entity_memory:
                    return dict(record.entity_memory)
                return {}

            always = [s for s in stores if s.inject == "always"]
            multi = len(always) > 1
            merged: dict[str, str] = {}
            for store_cfg in always:
                namespace = self._memory_store_namespace(store_cfg.name)
                record = await self.cross_session_memory_store.load(
                    self.run_context.tenant_id,
                    self.run_context.user_id,
                    namespace,
                    company_id=company_id,
                )
                if not record or not record.entity_memory:
                    continue
                entries = self._trim_to_char_budget(
                    dict(record.entity_memory), store_cfg.char_budget
                )
                for key, value in entries.items():
                    out_key = f"{store_cfg.name}/{key}" if multi else key
                    merged[out_key] = value
            return merged
        except Exception as exc:
            logger.warning("AgentRunner: failed to load cross-session memory: %s", exc)
            return {}

    async def _get_or_create_session(self, session_id: Optional[str]) -> AgentSession:
        """Fetch existing session or create a new one."""
        sid = session_id or self.run_context.session_id
        session = None
        if sid:
            session = await self.session_manager.load_session(
                sid, scope=self._session_scope()
            )

        if not session:
            session = await self.session_manager.create_session(
                agent_id=self.config.name,
                session_id=sid,
                scope=self._session_scope(),
                user_name=self.run_context.user_name,
            )
            self.run_context.session_id = session.session_id

        return session

    async def _maybe_curate_after_turn(
        self, session: AgentSession, turn_index: int
    ) -> AgentSession:
        """Run memory curator after a turn if configured; reload session."""
        if self.memory_curator.should_trigger(turn_index, at_end=False):
            await self.memory_curator.curate(session, turn_index)
            reloaded = await self.session_manager.load_session(
                session.session_id, scope=self._session_scope(session)
            )
            if reloaded is not None:
                session = reloaded
            self._user_memory = await self._load_user_memory()
        return session

    async def _build_context_messages(
        self,
        session: AgentSession,
        *,
        current_user_message: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Build LLM messages with user_memory, summary_text, and token budget."""
        return await self.ctx_builder.build(
            session=session,
            agent_config=self.config,
            current_user_message=current_user_message,
            token_budget=self.config.llm.context_window_tokens,
            user_memory=self._user_memory,
            summary_text=session.summary_text,
            run_context=self.run_context,
            skills_catalog=self._skills_catalog,
            explicit_skills_content=self._explicit_skills_content,
        )

    async def _maybe_compact_and_summarize(
        self,
        session: AgentSession,
        messages: list[dict[str, Any]],
        session_turn_index: int,
        *,
        current_user_message: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Run RCS compactor and context summarizer when thresholds are met; rebuild context.

        Returns the rebuilt messages and the number of tokens saved by the
        fallback compactor this call (0 when it didn't run or saved nothing).
        The inline interceptor savings are applied separately during tool
        execution and surfaced via ``ContextUpdate.tokens_saved``.
        """
        model = self.config.llm.model
        current_tokens = TokenCounter.count_messages(messages, model)
        context_window = self.config.llm.context_window_tokens
        compactor_tokens_saved = 0

        if self.config.rcs.fallback_compactor.enabled:
            if await self.compactor.should_trigger(session, current_tokens):
                result = await self.compactor.compact(session, session_turn_index)
                compactor_tokens_saved = result.get("tokens_saved", 0)
                messages = await self._build_context_messages(
                    session, current_user_message=current_user_message
                )
                current_tokens = TokenCounter.count_messages(messages, model)

        if self.context_summarizer.should_trigger(
            session, current_tokens, context_window
        ):
            await self.context_summarizer.summarize(session, session_turn_index)
            messages = await self._build_context_messages(
                session, current_user_message=current_user_message
            )

        return messages, compactor_tokens_saved

    async def _call_llm(
        self,
        *,
        stream: bool,
        messages: list[dict[str, Any]],
        tool_schemas: Optional[list[dict[str, Any]]],
        session: AgentSession,
        turn_index: int,
    ) -> AsyncIterator[Union[AgentStreamEvent, LLMResponse]]:
        """Invoke the LLM. Yields AgentStreamEvent deltas when streaming, then LLMResponse."""
        await self.event_emitter.emit(
            LLMCallStartedEvent(
                session_id=session.session_id,
                agent_id=self.config.name,
                turn_index=turn_index,
                provider=self.config.llm.provider,
                model=self.config.llm.model,
                messages_count=len(messages),
            )
        )

        llm_start = time.time()
        tools = tool_schemas if tool_schemas else None

        try:
            if not stream:
                llm_response = await self.llm_proxy.chat(messages=messages, tools=tools)
                await self.event_emitter.emit(
                    LLMCallCompletedEvent(
                        session_id=session.session_id,
                        agent_id=self.config.name,
                        turn_index=turn_index,
                        provider=self.config.llm.provider,
                        model=self.config.llm.model,
                        tokens_in=llm_response.usage.prompt_tokens,
                        tokens_out=llm_response.usage.completion_tokens,
                        duration_ms=int((time.time() - llm_start) * 1000),
                    )
                )
                yield llm_response
                return

            raw_stream = self.llm_proxy.chat_stream(messages=messages, tools=tools)
            if inspect.iscoroutine(raw_stream):
                raw_stream = await raw_stream
            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls_acc: dict[int, dict[str, Any]] = {}
            usage = TokenUsage()
            finish_reason = "stop"

            # Deltas are forwarded as they arrive so the caller can render them
            # live. Text that precedes a tool call is real assistant output (it is
            # persisted in the turn record either way), so it is streamed too.
            async for chunk in raw_stream:
                if chunk.reasoning:
                    reasoning_parts.append(chunk.reasoning)
                    await self.event_emitter.emit(
                        LLMStreamChunkEvent(
                            session_id=session.session_id,
                            agent_id=self.config.name,
                            turn_index=turn_index,
                            provider=self.config.llm.provider,
                            model=self.config.llm.model,
                            reasoning_delta=chunk.reasoning,
                            has_tool_call_delta=False,
                        )
                    )
                    yield AgentStreamEvent(
                        event_type="reasoning",
                        content=chunk.reasoning,
                        data={"agent_id": self.config.name, "turn_index": turn_index},
                    )

                if chunk.content:
                    content_parts.append(chunk.content)
                    await self.event_emitter.emit(
                        LLMStreamChunkEvent(
                            session_id=session.session_id,
                            agent_id=self.config.name,
                            turn_index=turn_index,
                            provider=self.config.llm.provider,
                            model=self.config.llm.model,
                            content_delta=chunk.content,
                            has_tool_call_delta=False,
                        )
                    )
                    yield AgentStreamEvent(
                        event_type="content",
                        content=chunk.content,
                        data={"agent_id": self.config.name, "turn_index": turn_index},
                    )

                if chunk.tool_calls:
                    for tc_delta in chunk.tool_calls:
                        _merge_tool_call_delta(tool_calls_acc, tc_delta)
                    await self.event_emitter.emit(
                        LLMStreamChunkEvent(
                            session_id=session.session_id,
                            agent_id=self.config.name,
                            turn_index=turn_index,
                            provider=self.config.llm.provider,
                            model=self.config.llm.model,
                            has_tool_call_delta=True,
                        )
                    )

                if chunk.usage:
                    usage = chunk.usage
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason

            llm_response = LLMResponse(
                content="".join(content_parts) if content_parts else None,
                reasoning="".join(reasoning_parts) if reasoning_parts else None,
                tool_calls=_tool_calls_from_accumulated(tool_calls_acc),
                usage=usage,
                finish_reason=finish_reason,
                raw_response={},
            )

            await self.event_emitter.emit(
                LLMCallCompletedEvent(
                    session_id=session.session_id,
                    agent_id=self.config.name,
                    turn_index=turn_index,
                    provider=self.config.llm.provider,
                    model=self.config.llm.model,
                    tokens_in=llm_response.usage.prompt_tokens,
                    tokens_out=llm_response.usage.completion_tokens,
                    duration_ms=int((time.time() - llm_start) * 1000),
                )
            )

            yield llm_response

        except Exception as e:
            await self.event_emitter.emit(
                LLMCallErrorEvent(
                    session_id=session.session_id,
                    agent_id=self.config.name,
                    turn_index=turn_index,
                    provider=self.config.llm.provider,
                    error=str(e),
                )
            )
            raise

    async def _run_loop(
        self,
        stream: bool,
        state: _LoopState,
        user_message: str,
        session_id: Optional[str] = None,
        initial_context: Optional[dict[str, Any]] = None,
        max_turns: Optional[int] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Shared agent loop. Yields AgentStreamEvents when stream=True."""
        session = await self._get_or_create_session(session_id)
        # Record whether RCS was enabled for this chat and persist before any
        # append_turn reload so the flag (read by the token_usage aggregate)
        # survives in the stored chat JSON.
        session.rcs_enabled = bool(getattr(self.config.rcs, "enabled", False))
        await self._maybe_save_session(session)
        self._user_memory = await self._load_user_memory()
        self._setup_skills()
        self._resolve_toolsets()
        await self._inject_learned_skills(user_message)

        self._hydrate_state_from_session(session, initial_context)
        if initial_context:
            session.metadata.update(initial_context)
            await self._maybe_save_session(session)

        await self.event_emitter.emit(
            AgentStartedEvent(
                agent_name=self.config.name,
                agent_id=self.config.name,
                session_id=session.session_id,
                user_message=user_message,
            )
        )

        if stream:
            yield AgentStreamEvent(
                event_type="event",
                content="Agent started execution.",
                data={"agent_id": self.config.name, "session_id": session.session_id},
            )

        start_time = time.time()
        session_turn_index = len(session.turns)
        run_turn_index = 0
        status = "completed"
        error_msg = None
        total_tokens_in = 0
        total_tokens_out = 0
        final_resp: Optional[str] = None
        turn_limit = self.config.turns.max_turns
        if max_turns is not None:
            turn_limit = min(turn_limit, max_turns)

        try:
            current_user_message = user_message

            while run_turn_index < turn_limit:
                turn_user_msg = current_user_message if run_turn_index == 0 else None
                messages = await self._build_context_messages(
                    session, current_user_message=turn_user_msg
                )
                messages, compactor_tokens_saved = await self._maybe_compact_and_summarize(
                    session,
                    messages,
                    session_turn_index,
                    current_user_message=turn_user_msg,
                )

                # Compute recurring RCS savings: how many input tokens RCS saved
                # this turn by having summarized/dropped TCs in context instead
                # of their raw versions. Accumulate into the session counter.
                recurring_savings_this_turn = self.ctx_builder.count_rcs_savings(
                    messages, session, self.config
                )
                session.cumulative_input_tokens_saved_by_rcs += recurring_savings_this_turn

                await self.event_emitter.emit(
                    TurnStartedEvent(
                        session_id=session.session_id,
                        agent_id=self.config.name,
                        turn_index=session_turn_index,
                        user_message=current_user_message if run_turn_index == 0 else None,
                    )
                )

                if stream:
                    yield AgentStreamEvent(
                        event_type="event",
                        content=f"Turn {session_turn_index} started.",
                        data={"agent_id": self.config.name, "turn_index": session_turn_index},
                    )

                # When a toolset allow-list is active it is the source of truth;
                # do not also filter by plugin namespaces (that would drop flat
                # tools with plugin="").
                plugin_names = (
                    None
                    if self._allowed_tools is not None
                    else self._effective_tool_plugins()
                )
                tool_schemas = self._filter_tool_schemas(
                    self.tool_registry.get_tool_schemas_for_llm(
                        plugin_names=plugin_names,
                        rcs_config=self.config.rcs,
                    )
                )

                llm_response: Optional[LLMResponse] = None
                async for item in self._call_llm(
                    stream=stream,
                    messages=messages,
                    tool_schemas=tool_schemas,
                    session=session,
                    turn_index=session_turn_index,
                ):
                    if isinstance(item, AgentStreamEvent):
                        yield item
                    else:
                        llm_response = item

                assert llm_response is not None
                llm_response = promote_content_tool_calls(llm_response)
                total_tokens_in += llm_response.usage.prompt_tokens
                total_tokens_out += llm_response.usage.completion_tokens

                if not llm_response.tool_calls and self.config.turns.stop_on_empty_tool_calls:
                    final_resp = llm_response.content
                    final_turn = TurnRecord(
                        turn_index=session_turn_index,
                        user_message=current_user_message if run_turn_index == 0 else None,
                        llm_messages=[
                            build_assistant_llm_message(
                                content=llm_response.content,
                                tool_calls=llm_response.tool_calls,
                            )
                        ],
                        reasoning=llm_response.reasoning,
                        tool_calls=[],
                        total_tokens_in=llm_response.usage.prompt_tokens,
                        total_tokens_out=llm_response.usage.completion_tokens,
                        recurring_savings_this_turn=recurring_savings_this_turn,
                        duration_ms=int((time.time() - start_time) * 1000),
                        status="completed",
                    )
                    session = await self._persist_turn_with_state(session, final_turn)
                    session = await self._maybe_curate_after_turn(session, session_turn_index)

                    decision = await self._invoke_turn_end_hook(
                        session,
                        session_turn_index,
                        run_turn_index,
                        [],
                        final_resp,
                    )
                    if decision and decision.action == "stop":
                        status = "interrupted"
                        break
                    if decision and decision.action == "inject" and decision.message:
                        current_user_message = decision.message
                        session_turn_index += 1
                        run_turn_index += 1
                        continue

                    if self._maybe_pause_for_human_in_loop(session, run_turn_index):
                        status = "paused"
                        await self._maybe_save_session(session)
                        if stream:
                            yield AgentStreamEvent(
                                event_type="paused",
                                data={
                                    "session_id": session.session_id,
                                    "pending_interactions": [
                                        p.model_dump(mode="json")
                                        for p in session.pending_interactions
                                    ],
                                },
                            )
                        break

                    session_turn_index += 1
                    run_turn_index += 1
                    break

                turn_tool_records = []
                tokens_saved_this_turn = compactor_tokens_saved
                all_updates = []

                for tc_req in llm_response.tool_calls:
                    clean_args, updates = await self.interceptor.intercept(
                        tool_name=tc_req.tool_name,
                        tool_input=tc_req.tool_input,
                        session=session,
                        current_turn_index=session_turn_index,
                        storage_adapter=self.session_manager,
                        rcs_config=self.config.rcs,
                    )
                    all_updates.extend([u.model_dump() for u in updates])
                    # Use the interceptor's per-update tokens_saved (computed with
                    # TokenCounter, same formula as session.total_tokens_saved_by_rcs)
                    # so turn.tokens_saved_this_turn ties out to the session counter.
                    tokens_saved_this_turn += sum(u.tokens_saved for u in updates)

                    session.next_tc_index()
                    tc_index = session.tc_counter
                    tc_id = f"TC{tc_index}"

                    if stream:
                        yield AgentStreamEvent(
                            event_type="tool_call",
                            data={
                                "agent_id": self.config.name,
                                "turn_index": session_turn_index,
                                "tool_name": tc_req.tool_name,
                                "tool_args": clean_args,
                                "tc_id": tc_id,
                            },
                        )

                    await self.event_emitter.emit(
                        ToolCallStartedEvent(
                            session_id=session.session_id,
                            agent_id=self.config.name,
                            turn_index=session_turn_index,
                            tool_name=tc_req.tool_name,
                            tool_args=clean_args,
                        )
                    )

                    execution = self.tool_registry.get_execution_mode(tc_req.tool_name)
                    call_id = getattr(tc_req, "id", "") or ""
                    if execution == "client" or tc_req.tool_name.endswith("request_user_input"):
                        kind = (
                            "elicitation"
                            if tc_req.tool_name.endswith("request_user_input")
                            else "client_tool"
                        )
                        pending = PendingInteraction(
                            tc_id=tc_id,
                            call_id=call_id,
                            tool_name=tc_req.tool_name,
                            args=clean_args,
                            kind=kind,
                        )
                        session.pending_interactions.append(pending)
                        tc_record = ToolCallRecord(
                            tc_id=tc_id,
                            tc_index=tc_index,
                            tool_name=tc_req.tool_name,
                            call_id=call_id,
                            tool_input=clean_args,
                            raw_response="",
                            tokens_raw=0,
                        )
                        turn_tool_records.append(tc_record)
                        if stream:
                            yield AgentStreamEvent(
                                event_type=(
                                    "elicitation" if kind == "elicitation" else "client_tool_call"
                                ),
                                data={
                                    "agent_id": self.config.name,
                                    "turn_index": session_turn_index,
                                    "tool_name": tc_req.tool_name,
                                    "tool_args": clean_args,
                                    "tc_id": tc_id,
                                    "call_id": call_id,
                                    "kind": kind,
                                },
                            )
                        status = "paused"
                        break

                    tool_start = time.time()
                    try:
                        parts = tc_req.tool_name.split(".")
                        plugin = parts[0]
                        tool = parts[1] if len(parts) > 1 else ""

                        raw_result = await self.tool_registry.execute(
                            plugin=plugin,
                            tool=tool,
                            args=clean_args,
                            run_context=self.run_context,
                        )
                        result_str = str(raw_result)

                        await self.event_emitter.emit(
                            ToolCallCompletedEvent(
                                session_id=session.session_id,
                                agent_id=self.config.name,
                                turn_index=session_turn_index,
                                tool_name=tc_req.tool_name,
                                tool_output_length=len(result_str),
                                duration_ms=int((time.time() - tool_start) * 1000),
                            )
                        )
                    except Exception as e:
                        result_str = f"Error executing tool {tc_req.tool_name}: {e}"
                        await self.event_emitter.emit(
                            ToolCallErrorEvent(
                                session_id=session.session_id,
                                agent_id=self.config.name,
                                turn_index=session_turn_index,
                                tool_name=tc_req.tool_name,
                                error=str(e),
                            )
                        )

                    if stream:
                        yield AgentStreamEvent(
                            event_type="tool_result",
                            content=result_str,
                            data={
                                "agent_id": self.config.name,
                                "turn_index": session_turn_index,
                                "tool_name": tc_req.tool_name,
                                "tc_id": tc_id,
                            },
                        )

                    tc_record = ToolCallRecord(
                        tc_id=tc_id,
                        tc_index=tc_index,
                        tool_name=tc_req.tool_name,
                        call_id=call_id,
                        tool_input=clean_args,
                        raw_response=result_str,
                        tokens_raw=TokenCounter.count_string(result_str, self.config.llm.model),
                    )
                    turn_tool_records.append(tc_record)

                llm_messages_to_save = [
                    build_assistant_llm_message(
                        content=llm_response.content,
                        tool_calls=llm_response.tool_calls,
                    )
                ]

                turn_status = "paused" if status == "paused" else "completed"
                turn_record = TurnRecord(
                    turn_index=session_turn_index,
                    user_message=current_user_message if run_turn_index == 0 else None,
                    llm_messages=llm_messages_to_save,
                    reasoning=llm_response.reasoning,
                    tool_calls=turn_tool_records,
                    context_updates_received=all_updates,
                    total_tokens_in=llm_response.usage.prompt_tokens,
                    total_tokens_out=llm_response.usage.completion_tokens,
                    tokens_saved_this_turn=tokens_saved_this_turn,
                    recurring_savings_this_turn=recurring_savings_this_turn,
                    duration_ms=int((time.time() - start_time) * 1000),
                    status=turn_status,
                )

                session = await self._persist_turn_with_state(session, turn_record)
                if status == "paused":
                    await self._maybe_save_session(session)
                    if stream:
                        yield AgentStreamEvent(
                            event_type="paused",
                            data={
                                "session_id": session.session_id,
                                "pending_interactions": [
                                    p.model_dump(mode="json")
                                    for p in session.pending_interactions
                                ],
                            },
                        )
                    break
                session = await self._maybe_curate_after_turn(session, session_turn_index)

                tool_result_summaries = [
                    {"tool_name": tc.tool_name, "content": tc.raw_response}
                    for tc in turn_tool_records
                ]
                turn_final = None
                if not llm_response.tool_calls:
                    turn_final = llm_response.content

                await self.event_emitter.emit(
                    TurnCompletedEvent(
                        session_id=session.session_id,
                        agent_id=self.config.name,
                        turn_index=session_turn_index,
                        tool_calls_count=len(turn_tool_records),
                        tokens_in=llm_response.usage.prompt_tokens,
                        tokens_out=llm_response.usage.completion_tokens,
                        tokens_saved=tokens_saved_this_turn,
                        recurring_savings=recurring_savings_this_turn,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                )

                decision = await self._invoke_turn_end_hook(
                    session,
                    session_turn_index,
                    run_turn_index,
                    tool_result_summaries,
                    turn_final,
                )
                if decision and decision.action == "stop":
                    status = "interrupted"
                    break
                if decision and decision.action == "inject" and decision.message:
                    current_user_message = decision.message
                    session_turn_index += 1
                    run_turn_index += 1
                    continue

                if self._maybe_pause_for_human_in_loop(session, run_turn_index):
                    status = "paused"
                    await self._maybe_save_session(session)
                    if stream:
                        yield AgentStreamEvent(
                            event_type="paused",
                            data={
                                "session_id": session.session_id,
                                "pending_interactions": [
                                    p.model_dump(mode="json")
                                    for p in session.pending_interactions
                                ],
                            },
                        )
                    break

                session_turn_index += 1
                run_turn_index += 1

            if run_turn_index >= turn_limit:
                status = "max_turns_reached"

        except Exception as e:
            status = "error"
            error_msg = str(e)
            logger.exception("AgentRunner run error: %s", e)
            await self.event_emitter.emit(
                AgentErrorEvent(
                    session_id=session.session_id,
                    agent_id=self.config.name,
                    error=error_msg,
                )
            )
            if stream:
                yield AgentStreamEvent(
                    event_type="error",
                    content=error_msg,
                    data={"agent_id": self.config.name, "status": "error"},
                )

        if status != "error" and self.memory_curator.active:
            try:
                refreshed = await self.session_manager.load_session(
                    session.session_id, scope=self._session_scope(session)
                )
                if refreshed is not None:
                    session = refreshed
                final_turn_idx = max(session_turn_index - 1, 0)
                if self.memory_curator.should_trigger(final_turn_idx, at_end=True):
                    await self.memory_curator.curate(session, final_turn_idx)
                    self._user_memory = await self._load_user_memory()
            except Exception as e:
                logger.warning("AgentRunner: end-of-run memory curation failed: %s", e)

        duration_ms = int((time.time() - start_time) * 1000)

        if final_resp is None and session.turns:
            last_turn = session.turns[-1]
            for msg in last_turn.llm_messages:
                if msg.get("role") == "assistant" and msg.get("content"):
                    final_resp = msg["content"]

        snapshot = self._json_safe_state(dict(self.run_context.state))
        session.state = snapshot
        self.run_context.state = dict(snapshot)
        await self._maybe_save_session(session)

        run_result = AgentRunResult(
            session_id=session.session_id,
            final_response=final_resp,
            turns_used=run_turn_index,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=session.total_tokens_saved_by_rcs,
            cumulative_input_tokens_saved_by_rcs=session.cumulative_input_tokens_saved_by_rcs,
            duration_ms=duration_ms,
            status=status,  # type: ignore[arg-type]
            error=error_msg,
            pending_interactions=[
                p.model_dump(mode="json") for p in session.pending_interactions
            ],
            state=dict(snapshot),
        )
        state.result = run_result

        await self.event_emitter.emit(
            AgentCompletedEvent(
                session_id=session.session_id,
                agent_id=self.config.name,
                turns_used=run_turn_index,
                total_tokens_in=total_tokens_in,
                total_tokens_out=total_tokens_out,
                total_tokens_saved_by_rcs=session.total_tokens_saved_by_rcs,
                cumulative_tokens_saved_by_rcs=session.cumulative_input_tokens_saved_by_rcs,
            )
        )

        if stream:
            yield AgentStreamEvent(
                event_type="final_response",
                content=final_resp,
                data=run_result.model_dump(),
            )

    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        initial_context: Optional[dict[str, Any]] = None,
        stream: Optional[bool] = None,
        max_turns: Optional[int] = None,
    ) -> AgentRunResult:
        """Run the agent loop and return the complete result (non-streaming mode)."""
        if self._resolve_stream(stream):
            raise ValueError(
                "Streaming mode enabled; use run_stream() or pass stream=False."
            )

        state = _LoopState()
        async for _ in self._run_loop(
            stream=False,
            state=state,
            user_message=user_message,
            session_id=session_id,
            initial_context=initial_context,
            max_turns=max_turns,
        ):
            pass

        assert state.result is not None
        return state.result

    async def run_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        initial_context: Optional[dict[str, Any]] = None,
        stream: Optional[bool] = None,
        max_turns: Optional[int] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Run the agent loop in streaming mode, yielding incremental events."""
        if not self._resolve_stream(stream):
            raise ValueError(
                "Non-streaming mode; use run() or pass stream=True."
            )

        state = _LoopState()
        async for event in self._run_loop(
            stream=True,
            state=state,
            user_message=user_message,
            session_id=session_id,
            initial_context=initial_context,
            max_turns=max_turns,
        ):
            yield event

        assert state.result is not None

    async def resume(
        self,
        session_id: str,
        results: list[dict[str, Any]],
        *,
        stream: Optional[bool] = None,
    ) -> AgentRunResult:
        """Resume a paused run after client tools / elicitations return.

        ``results`` items: ``{"tc_id"|"call_id": ..., "content": "..."}``.
        """
        session = await self.session_manager.load_session(
            session_id, scope=self._session_scope()
        )
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        if not session.pending_interactions:
            raise ValueError("Session has no pending interactions to resume")

        # Map results onto pending interactions and fill empty tool responses
        by_tc = {r.get("tc_id"): r for r in results if r.get("tc_id")}
        by_call = {r.get("call_id"): r for r in results if r.get("call_id")}
        for pending in list(session.pending_interactions):
            match = by_tc.get(pending.tc_id) or by_call.get(pending.call_id)
            content = (match or {}).get("content", "")
            for turn in reversed(session.turns):
                for tc in turn.tool_calls:
                    if tc.tc_id == pending.tc_id and not tc.raw_response:
                        tc.raw_response = str(content)
                        break
        session.pending_interactions = []
        await self._maybe_save_session(session)

        if self._resolve_stream(stream):
            loop_state = _LoopState()
            async for _ in self._run_loop(
                stream=True,
                state=loop_state,
                user_message="",
                session_id=session_id,
                initial_context=None,
            ):
                pass
            assert loop_state.result is not None
            return loop_state.result

        return await self.run(
            user_message="",
            session_id=session_id,
            stream=False,
        )
