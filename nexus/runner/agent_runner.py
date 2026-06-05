"""Agent Runner orchestrating the main agentic loop with RCS."""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Union

from nexus.config.agent import AgentConfig
from nexus.config.storage import SessionStorageConfig
from nexus.context.builder import ContextWindowBuilder
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
from nexus.llm.response import LLMResponse, TokenUsage, ToolCallRequest
from nexus.llm.tool_format import tool_calls_to_openai_messages
from nexus.llm.token_counter import TokenCounter
from nexus.memory.curator import MemoryCurator
from nexus.memory.cross_session_store import (
    CrossSessionMemoryStore,
    resolve_cross_session_namespace,
)
from nexus.rcs.compactor import ServerCompactor
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord
from nexus.skills.catalog import build_explicit_skills_block, build_skills_catalog
from nexus.skills.plugin import create_skills_plugin
from nexus.skills.registry import SkillsRegistry
from nexus.tools.context import RunContext
from nexus.tools.interceptor import ContextUpdateInterceptor
from nexus.tools.registry import ToolRegistry

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
        if not tc.get("id") or not tc.get("name"):
            continue
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
        self._cross_session_entity_memory: dict[str, str] = {}

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
            config=self.config.session_memory,
            llm_proxy=self.llm_proxy,
            session_manager=self.session_manager,
            tool_registry=self.tool_registry,
            run_context=self.run_context,
            event_emitter=self.event_emitter,
            cross_session_memory_store=self.cross_session_memory_store,
            agent_name=self.config.name,
        )

        self.skills_registry: Optional[SkillsRegistry] = None
        self._skills_catalog: Optional[str] = None
        self._explicit_skills_content: Optional[str] = None
        if self.config.skills.enabled:
            self.skills_registry = SkillsRegistry(self.config.skills)

    def _resolve_stream(self, stream: Optional[bool]) -> bool:
        """Resolve effective streaming mode from per-call override or config default."""
        return self.config.stream_output if stream is None else stream

    def _session_lookup_kwargs(
        self, session: Optional[AgentSession] = None
    ) -> dict[str, Optional[str]]:
        """Tenant/user hints for tenant-scoped storage adapters."""
        return {
            "tenant_id": self.run_context.tenant_id
            or (session.tenant_id if session else None),
            "user_id": self.run_context.user_id or (session.user_id if session else None),
        }

    def _effective_tool_plugins(self) -> list[str]:
        """Return tool plugin allow-list, auto-including skills when enabled."""
        plugins = list(self.config.tool_plugins)
        if self.config.skills.enabled and "skills" not in plugins:
            plugins.append("skills")
        return plugins

    def _setup_skills(self) -> None:
        """Register skills plugin and prepare prompt injection content."""
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

    def _filter_tool_schemas(self, tool_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Hide run_skill_script unless scripts are enabled and present."""
        if not self.skills_registry:
            return tool_schemas
        expose_scripts = (
            self.config.skills.allow_scripts
            and self.skills_registry.has_scripts(self.run_context)
        )
        if expose_scripts:
            return tool_schemas
        return [s for s in tool_schemas if s.get("name") != "skills.run_skill_script"]

    async def _load_cross_session_entity_memory(self) -> dict[str, str]:
        """Load cross-session facts for injection into the system prompt."""
        cross_cfg = self.config.session_memory.cross_session
        if not cross_cfg.enabled or not self.cross_session_memory_store:
            return {}
        if not self.run_context.user_id:
            return {}

        namespace = resolve_cross_session_namespace(cross_cfg.namespace, self.config.name)
        try:
            record = await self.cross_session_memory_store.load(
                self.run_context.tenant_id,
                self.run_context.user_id,
                namespace,
            )
            if record and record.entity_memory:
                return dict(record.entity_memory)
        except Exception as exc:
            logger.warning("AgentRunner: failed to load cross-session memory: %s", exc)
        return {}

    async def _get_or_create_session(self, session_id: Optional[str]) -> AgentSession:
        """Fetch existing session or create a new one."""
        sid = session_id or self.run_context.session_id
        session = None
        if sid:
            session = await self.session_manager.load_session(
                sid, **self._session_lookup_kwargs()
            )

        if not session:
            session = await self.session_manager.create_session(
                agent_id=self.config.name,
                session_id=sid,
                tenant_id=self.run_context.tenant_id,
                user_id=self.run_context.user_id,
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
                session.session_id, **self._session_lookup_kwargs(session)
            )
            if reloaded is not None:
                session = reloaded
            self._cross_session_entity_memory = await self._load_cross_session_entity_memory()
        return session

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

            raw_stream = await self.llm_proxy.chat_stream(messages=messages, tools=tools)
            content_parts: list[str] = []
            content_buffer: list[str] = []
            tool_calls_acc: dict[int, dict[str, Any]] = {}
            usage = TokenUsage()
            finish_reason = "stop"

            async for chunk in raw_stream:
                if chunk.content:
                    content_parts.append(chunk.content)
                    content_buffer.append(chunk.content)

                if chunk.tool_calls:
                    content_buffer.clear()
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

            if not llm_response.tool_calls:
                for delta in content_buffer:
                    await self.event_emitter.emit(
                        LLMStreamChunkEvent(
                            session_id=session.session_id,
                            agent_id=self.config.name,
                            turn_index=turn_index,
                            provider=self.config.llm.provider,
                            model=self.config.llm.model,
                            content_delta=delta,
                            has_tool_call_delta=False,
                        )
                    )
                    yield AgentStreamEvent(
                        event_type="content",
                        content=delta,
                        data={"agent_id": self.config.name, "turn_index": turn_index},
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
    ) -> AsyncIterator[AgentStreamEvent]:
        """Shared agent loop. Yields AgentStreamEvents when stream=True."""
        session = await self._get_or_create_session(session_id)
        self._cross_session_entity_memory = await self._load_cross_session_entity_memory()
        self._setup_skills()

        if initial_context:
            session.metadata.update(initial_context)
            await self.session_manager.save_session(session)

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

        try:
            current_user_message = user_message

            while run_turn_index < self.config.turns.max_turns:
                messages = self.ctx_builder.build(
                    session=session,
                    agent_config=self.config,
                    current_user_message=current_user_message if run_turn_index == 0 else None,
                    token_budget=self.config.llm.context_window_tokens,
                    cross_session_entity_memory=self._cross_session_entity_memory,
                    skills_catalog=self._skills_catalog,
                    explicit_skills_content=self._explicit_skills_content,
                )
                current_tokens = TokenCounter.count_messages(messages, self.config.llm.model)

                if self.config.rcs.fallback_compactor.enabled:
                    if await self.compactor.should_trigger(session, current_tokens):
                        await self.compactor.compact(session, session_turn_index)
                        messages = self.ctx_builder.build(
                            session=session,
                            agent_config=self.config,
                            current_user_message=current_user_message if run_turn_index == 0 else None,
                            skills_catalog=self._skills_catalog,
                            explicit_skills_content=self._explicit_skills_content,
                        )

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

                tool_schemas = self._filter_tool_schemas(
                    self.tool_registry.get_tool_schemas_for_llm(
                        plugin_names=self._effective_tool_plugins(),
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
                total_tokens_in += llm_response.usage.prompt_tokens
                total_tokens_out += llm_response.usage.completion_tokens

                if not llm_response.tool_calls and self.config.turns.stop_on_empty_tool_calls:
                    final_resp = llm_response.content
                    final_turn = TurnRecord(
                        turn_index=session_turn_index,
                        user_message=current_user_message if run_turn_index == 0 else None,
                        llm_messages=[{"role": "assistant", "content": llm_response.content}],
                        tool_calls=[],
                        total_tokens_in=llm_response.usage.prompt_tokens,
                        total_tokens_out=llm_response.usage.completion_tokens,
                        duration_ms=int((time.time() - start_time) * 1000),
                        status="completed",
                    )
                    await self.session_manager.append_turn(
                        session.session_id,
                        final_turn,
                        **self._session_lookup_kwargs(session),
                    )
                    session = await self.session_manager.load_session(
                        session.session_id, **self._session_lookup_kwargs(session)
                    )
                    session = await self._maybe_curate_after_turn(session, session_turn_index)
                    session_turn_index += 1
                    run_turn_index += 1
                    break

                turn_tool_records = []
                tokens_saved_this_turn = 0
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
                    tokens_saved_this_turn += sum(
                        max(0, session.find_tc(u.tc_id).tokens_raw - len(u.summary.split()))
                        for u in updates if session.find_tc(u.tc_id)
                    )

                    tc_id = f"TC{session.next_tc_index()}"

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
                        tc_index=session.tc_counter,
                        tool_name=tc_req.tool_name,
                        tool_input=clean_args,
                        raw_response=result_str,
                        tokens_raw=TokenCounter.count_string(result_str, self.config.llm.model),
                    )
                    turn_tool_records.append(tc_record)

                llm_messages_to_save = [
                    {
                        "role": "assistant",
                        "content": llm_response.content,
                        "tool_calls": (
                            tool_calls_to_openai_messages(llm_response.tool_calls)
                            if llm_response.tool_calls
                            else None
                        ),
                    }
                ]

                turn_record = TurnRecord(
                    turn_index=session_turn_index,
                    user_message=current_user_message if run_turn_index == 0 else None,
                    llm_messages=llm_messages_to_save,
                    tool_calls=turn_tool_records,
                    context_updates_received=all_updates,
                    total_tokens_in=llm_response.usage.prompt_tokens,
                    total_tokens_out=llm_response.usage.completion_tokens,
                    tokens_saved_this_turn=tokens_saved_this_turn,
                    duration_ms=int((time.time() - start_time) * 1000),
                    status="completed",
                )

                await self.session_manager.append_turn(
                    session.session_id,
                    turn_record,
                    **self._session_lookup_kwargs(session),
                )
                session = await self.session_manager.load_session(
                    session.session_id, **self._session_lookup_kwargs(session)
                )
                session = await self._maybe_curate_after_turn(session, session_turn_index)

                await self.event_emitter.emit(
                    TurnCompletedEvent(
                        session_id=session.session_id,
                        agent_id=self.config.name,
                        turn_index=session_turn_index,
                        tool_calls_count=len(turn_tool_records),
                        tokens_in=llm_response.usage.prompt_tokens,
                        tokens_out=llm_response.usage.completion_tokens,
                        tokens_saved=tokens_saved_this_turn,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                )

                session_turn_index += 1
                run_turn_index += 1

            if run_turn_index >= self.config.turns.max_turns:
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
                    session.session_id, **self._session_lookup_kwargs(session)
                )
                if refreshed is not None:
                    session = refreshed
                final_turn_idx = max(session_turn_index - 1, 0)
                if self.memory_curator.should_trigger(final_turn_idx, at_end=True):
                    await self.memory_curator.curate(session, final_turn_idx)
                    self._cross_session_entity_memory = await self._load_cross_session_entity_memory()
            except Exception as e:
                logger.warning("AgentRunner: end-of-run memory curation failed: %s", e)

        duration_ms = int((time.time() - start_time) * 1000)

        if final_resp is None and session.turns:
            last_turn = session.turns[-1]
            for msg in last_turn.llm_messages:
                if msg.get("role") == "assistant" and msg.get("content"):
                    final_resp = msg["content"]

        run_result = AgentRunResult(
            session_id=session.session_id,
            final_response=final_resp,
            turns_used=run_turn_index,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=session.total_tokens_saved_by_rcs,
            duration_ms=duration_ms,
            status=status,
            error=error_msg,
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
        ):
            pass

        assert state.result is not None
        return state.result

    async def run_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        stream: Optional[bool] = None,
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
            initial_context=None,
        ):
            yield event

        assert state.result is not None
