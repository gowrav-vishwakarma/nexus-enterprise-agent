"""Agent Runner orchestrating the main agentic loop with RCS."""

import asyncio
import logging
import time
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
)
from nexus.llm.proxy import LLMProxy
from nexus.llm.response import LLMResponse, ToolCallRequest
from nexus.llm.tool_format import tool_calls_to_openai_messages
from nexus.llm.token_counter import TokenCounter
from nexus.rcs.compactor import ServerCompactor
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord
from nexus.tools.context import RunContext
from nexus.tools.interceptor import ContextUpdateInterceptor
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentRunner:
    """Orchestrates single-agent execution loops, handling state, tools, and RCS."""

    def __init__(
        self,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        storage_config: Optional[Union[SessionStorageConfig, SessionManager]] = None,
        run_context: Optional[RunContext] = None,
        event_emitter: Optional[NexusEventEmitter] = None,
    ):
        self.config = config
        self.tool_registry = tool_registry
        
        # Load or initialize Session Manager
        if isinstance(storage_config, SessionManager):
            self.session_manager = storage_config
        elif isinstance(storage_config, SessionStorageConfig):
            self.session_manager = SessionManager.from_config(storage_config)
        else:
            # Check if agent has storage config in config object
            if self.config.storage:
                self.session_manager = SessionManager.from_config(self.config.storage)
            else:
                self.session_manager = SessionManager()

        self.run_context = run_context or RunContext()
        
        # Initialize Event System
        self.event_emitter = event_emitter or NexusEventEmitter()
        if self.config.trace_enabled and not self.event_emitter._sinks:
            if self.config.trace_sink == "stdout":
                self.event_emitter.register_sink(StdoutEventSink())
            elif self.config.trace_sink == "otel":
                from nexus.events.emitter import OTelEventSink
                self.event_emitter.register_sink(OTelEventSink())

        # Initialize LLM proxy, context builder, interceptor, and compactor
        self.llm_proxy = LLMProxy(self.config.llm)
        self.ctx_builder = ContextWindowBuilder(event_emitter=self.event_emitter)
        self.interceptor = ContextUpdateInterceptor(event_emitter=self.event_emitter)
        self.compactor = ServerCompactor(
            config=self.config.rcs.fallback_compactor,
            llm_proxy=self.llm_proxy,
            storage_adapter=self.session_manager,
            event_emitter=self.event_emitter,
        )

    async def _get_or_create_session(self, session_id: Optional[str]) -> AgentSession:
        """Fetch existing session or create a new one."""
        sid = session_id or self.run_context.session_id
        session = None
        if sid:
            session = await self.session_manager.load_session(sid)
        
        if not session:
            session = await self.session_manager.create_session(
                agent_id=self.config.name,
                session_id=sid,
                tenant_id=self.run_context.tenant_id,
                user_id=self.run_context.user_id,
            )
            # Sync session_id back to run_context
            self.run_context.session_id = session.session_id
            
        return session

    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        initial_context: Optional[dict[str, Any]] = None,
    ) -> AgentRunResult:
        """Run the single agent turn-loop synchronously (awaiting entire flow)."""
        session = await self._get_or_create_session(session_id)
        
        # Set initial metadata if provided
        if initial_context:
            session.metadata.update(initial_context)
            await self.session_manager.save_session(session)

        # Emit Agent Run Started Event
        await self.event_emitter.emit(
            AgentStartedEvent(
                agent_name=self.config.name,
                agent_id=self.config.name,
                session_id=session.session_id,
                user_message=user_message,
            )
        )

        start_time = time.time()
        turn_index = 0
        status = "completed"
        error_msg = None
        total_tokens_in = 0
        total_tokens_out = 0
        final_resp: Optional[str] = None

        try:
            # We seed the conversation loop with user_message if this is the first turn
            current_user_message = user_message

            while turn_index < self.config.turns.max_turns:
                # ── 1. BUILD CONTEXT WINDOW ──
                # Build prompt with tagged unsummarized, plain summarized, or omitted dropped results
                messages = self.ctx_builder.build(
                    session=session,
                    agent_config=self.config,
                    current_user_message=current_user_message if turn_index == 0 else None,
                    token_budget=self.config.llm.context_window_tokens,
                )
                current_tokens = TokenCounter.count_messages(messages, self.config.llm.model)

                # ── 2. FALLBACK COMPACTOR ──
                if self.config.rcs.fallback_compactor.enabled:
                    if await self.compactor.should_trigger(session, current_tokens):
                        await self.compactor.compact(session, turn_index)
                        # Rebuild messages list with newly compacted responses
                        messages = self.ctx_builder.build(
                            session=session,
                            agent_config=self.config,
                            current_user_message=current_user_message if turn_index == 0 else None,
                        )

                # Emit Turn Started Event
                await self.event_emitter.emit(
                    TurnStartedEvent(
                        session_id=session.session_id,
                        agent_id=self.config.name,
                        turn_index=turn_index,
                        user_message=current_user_message if turn_index == 0 else None,
                    )
                )

                # ── 3. CALL LLM ──
                tool_schemas = self.tool_registry.get_tool_schemas_for_llm(
                    plugin_names=self.config.tool_plugins,
                    rcs_config=self.config.rcs,
                )

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
                try:
                    llm_response = await self.llm_proxy.chat(
                        messages=messages,
                        tools=tool_schemas if tool_schemas else None,
                    )
                    
                    total_tokens_in += llm_response.usage.prompt_tokens
                    total_tokens_out += llm_response.usage.completion_tokens
                    
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

                # ── 4. STOP CONDITIONS: save final-response turn, then break ──
                if not llm_response.tool_calls and self.config.turns.stop_on_empty_tool_calls:
                    final_resp = llm_response.content
                    final_turn = TurnRecord(
                        turn_index=turn_index,
                        user_message=current_user_message if turn_index == 0 else None,
                        llm_messages=[{"role": "assistant", "content": llm_response.content}],
                        tool_calls=[],
                        total_tokens_in=llm_response.usage.prompt_tokens,
                        total_tokens_out=llm_response.usage.completion_tokens,
                        duration_ms=int((time.time() - start_time) * 1000),
                        status="completed",
                    )
                    await self.session_manager.append_turn(session.session_id, final_turn)
                    turn_index += 1
                    break

                # ── 5. PROCESS TOOL CALLS ──
                turn_tool_records = []
                tokens_saved_this_turn = 0
                all_updates = []

                for tc_req in llm_response.tool_calls:
                    # 5a. Intercept _context_updates before tool executes
                    clean_args, updates = await self.interceptor.intercept(
                        tool_name=tc_req.tool_name,
                        tool_input=tc_req.tool_input,
                        session=session,
                        current_turn_index=turn_index,
                        storage_adapter=self.session_manager,
                        rcs_config=self.config.rcs,
                    )
                    all_updates.extend([u.model_dump() for u in updates])
                    tokens_saved_this_turn += sum(
                        max(0, session.find_tc(u.tc_id).tokens_raw - len(u.summary.split()))  # Rough estimation
                        for u in updates if session.find_tc(u.tc_id)
                    )

                    # 5b. Assign Turn Index and TC ID
                    tc_id = f"TC{session.next_tc_index()}"

                    # Emit Tool call start event
                    await self.event_emitter.emit(
                        ToolCallStartedEvent(
                            session_id=session.session_id,
                            agent_id=self.config.name,
                            turn_index=turn_index,
                            tool_name=tc_req.tool_name,
                            tool_args=clean_args,
                        )
                    )

                    tool_start = time.time()
                    try:
                        # 5c. Execute Tool
                        # Tool name is plugin_name.tool_name
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
                                turn_index=turn_index,
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
                                turn_index=turn_index,
                                tool_name=tc_req.tool_name,
                                error=str(e),
                            )
                        )

                    # 5d. Store ToolCallRecord
                    tc_record = ToolCallRecord(
                        tc_id=tc_id,
                        tc_index=session.tc_counter,
                        tool_name=tc_req.tool_name,
                        tool_input=clean_args,
                        raw_response=result_str,
                        tokens_raw=TokenCounter.count_string(result_str, self.config.llm.model),
                    )
                    turn_tool_records.append(tc_record)

                # Format LLM messages safely (handling serialization)
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

                # ── 6. BUILD AND SAVE TURN RECORD ──
                turn_record = TurnRecord(
                    turn_index=turn_index,
                    user_message=current_user_message if turn_index == 0 else None,
                    llm_messages=llm_messages_to_save,
                    tool_calls=turn_tool_records,
                    context_updates_received=all_updates,
                    total_tokens_in=llm_response.usage.prompt_tokens,
                    total_tokens_out=llm_response.usage.completion_tokens,
                    tokens_saved_this_turn=tokens_saved_this_turn,
                    duration_ms=int((time.time() - start_time) * 1000),
                    status="completed",
                )
                
                await self.session_manager.append_turn(session.session_id, turn_record)
                
                # Fetch fresh session state from persistence to reflect append
                session = await self.session_manager.load_session(session.session_id)

                await self.event_emitter.emit(
                    TurnCompletedEvent(
                        session_id=session.session_id,
                        agent_id=self.config.name,
                        turn_index=turn_index,
                        tool_calls_count=len(turn_tool_records),
                        tokens_in=llm_response.usage.prompt_tokens,
                        tokens_out=llm_response.usage.completion_tokens,
                        tokens_saved=tokens_saved_this_turn,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                )

                turn_index += 1
                
            if turn_index >= self.config.turns.max_turns:
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

        duration_ms = int((time.time() - start_time) * 1000)

        # Pull final response — prefer the directly tracked value; fall back to session scan
        if final_resp is None and session.turns:
            last_turn = session.turns[-1]
            for msg in last_turn.llm_messages:
                if msg.get("role") == "assistant" and msg.get("content"):
                    final_resp = msg["content"]

        run_result = AgentRunResult(
            session_id=session.session_id,
            final_response=final_resp,
            turns_used=turn_index,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=session.total_tokens_saved_by_rcs,
            duration_ms=duration_ms,
            status=status,
            error=error_msg,
        )

        await self.event_emitter.emit(
            AgentCompletedEvent(
                session_id=session.session_id,
                agent_id=self.config.name,
                turns_used=turn_index,
                total_tokens_in=total_tokens_in,
                total_tokens_out=total_tokens_out,
                total_tokens_saved_by_rcs=session.total_tokens_saved_by_rcs,
            )
        )

        return run_result

    async def run_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Run the single agent loop in streaming mode, yielding tokens and events."""
        # Yield start event placeholder
        yield AgentStreamEvent(event_type="event", content="Agent started execution.")
        
        # Simple fallback execution utilizing synchronous chat + streaming simulations
        # For simplicity and robust usage, execute chat and yield events.
        result = await self.run(user_message, session_id)
        if result.final_response:
            yield AgentStreamEvent(event_type="content", content=result.final_response)
        
        yield AgentStreamEvent(
            event_type="final_response",
            content=result.final_response,
            data=result.model_dump(),
        )
