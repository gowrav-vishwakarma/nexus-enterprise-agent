"""Agent orchestrator for executing multi-agent patterns."""

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Optional, Union

from nexus.config.agent import AgentConfig, AgentGroupConfig
from nexus.multiagent.results import AgentGroupResult
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.result import AgentRunResult, AgentStreamEvent
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates recursive multi-agent structures using groups and patterns."""

    def __init__(
        self,
        config: AgentGroupConfig,
        tool_registry: Optional[ToolRegistry] = None,
        storage_config: Optional[Any] = None,
        run_context: Optional[RunContext] = None,
        cross_session_memory_store: Optional[Any] = None,
    ):
        self.config = config
        self.tool_registry = tool_registry or ToolRegistry()
        self.storage_config = storage_config
        self.run_context = run_context or RunContext()
        self.cross_session_memory_store = cross_session_memory_store
        self._init_members()

    def _resolve_stream(self, stream: Optional[bool]) -> bool:
        """Resolve effective streaming mode from per-call override or group config."""
        return self.config.stream_output if stream is None else stream

    def _init_members(self) -> None:
        """Initialize runners/orchestrators for all group members recursively."""
        self._members: dict[str, Union[AgentRunner, "AgentOrchestrator"]] = {}

        for member in self.config.members:
            m_ctx = RunContext(
                tenant_id=self.run_context.tenant_id,
                user_id=self.run_context.user_id,
                session_id=(
                    f"{self.config.session_id_prefix}{self.run_context.session_id}_{member.name}"
                    if self.run_context.session_id
                    else None
                ),
            )

            if isinstance(member, AgentConfig):
                runner = AgentRunner(
                    config=member,
                    tool_registry=self.tool_registry,
                    storage_config=self.storage_config,
                    run_context=m_ctx,
                    cross_session_memory_store=self.cross_session_memory_store,
                )
                self._members[member.name] = runner
            elif isinstance(member, AgentGroupConfig):
                nested_orc = AgentOrchestrator(
                    config=member,
                    tool_registry=self.tool_registry,
                    storage_config=self.storage_config,
                    run_context=m_ctx,
                    cross_session_memory_store=self.cross_session_memory_store,
                )
                self._members[member.name] = nested_orc

    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        stream: Optional[bool] = None,
    ) -> AgentGroupResult:
        """Execute the multi-agent group pattern recursively (non-streaming)."""
        if self._resolve_stream(stream):
            raise ValueError(
                "Streaming mode enabled; use run_stream() or pass stream=False."
            )

        start_time = time.time()

        if session_id:
            self.run_context.session_id = session_id

        if self.config.pattern == "pipeline":
            return await self._run_pipeline(user_message, start_time, stream=False)
        elif self.config.pattern == "supervisor":
            return await self._run_supervisor(user_message, start_time, stream=False)
        elif self.config.pattern == "parallel":
            return await self._run_parallel(user_message, start_time)
        else:
            return await self._run_pipeline(user_message, start_time, stream=False)

    async def run_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        stream: Optional[bool] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Execute the group in streaming mode, yielding multiplexed member events."""
        if not self._resolve_stream(stream):
            raise ValueError(
                "Non-streaming mode; use run() or pass stream=True."
            )

        if session_id:
            self.run_context.session_id = session_id

        yield AgentStreamEvent(
            event_type="event",
            content=f"Agent group '{self.config.name}' started.",
            data={"group": self.config.name, "pattern": self.config.pattern},
        )

        if self.config.pattern == "supervisor":
            async for event in self._run_supervisor_stream(user_message):
                yield event
        elif self.config.pattern == "parallel":
            async for event in self._run_parallel_stream(user_message):
                yield event
        else:
            async for event in self._run_pipeline_stream(user_message):
                yield event

    def _tag_member_event(self, member_name: str, event: AgentStreamEvent) -> AgentStreamEvent:
        """Attach member identity to a delegated stream event."""
        data = dict(event.data or {})
        data["member"] = member_name
        data["group"] = self.config.name
        return AgentStreamEvent(
            event_type=event.event_type,
            content=event.content,
            data=data,
        )

    def _root_session_id(self) -> str:
        """Root chat session id shared across all group members."""
        return self.run_context.session_id or ""

    async def _run_pipeline(
        self,
        user_message: str,
        start_time: float,
        *,
        stream: bool,
    ) -> AgentGroupResult:
        """Pipeline pattern: output of member N becomes input to member N+1."""
        current_input = user_message
        member_results: dict[str, Any] = {}
        turns_used = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_tokens_saved = 0

        for name, member in self._members.items():
            logger.info("Pipeline: Executing member '%s'", name)

            try:
                if isinstance(member, AgentRunner):
                    if stream:
                        raise ValueError("Use run_stream() for streaming pipeline execution.")
                    res = await member.run(current_input, stream=False)
                    member_results[name] = res
                    current_input = res.final_response or ""
                    turns_used += res.turns_used
                    total_tokens_in += res.total_tokens_in
                    total_tokens_out += res.total_tokens_out
                    total_tokens_saved += res.total_tokens_saved_by_rcs
                elif isinstance(member, AgentOrchestrator):
                    if stream:
                        raise ValueError("Use run_stream() for streaming pipeline execution.")
                    res = await member.run(current_input, stream=False)
                    member_results[name] = res
                    current_input = res.final_response or ""
                    turns_used += res.turns_used
                    total_tokens_in += res.total_tokens_in
                    total_tokens_out += res.total_tokens_out
                    total_tokens_saved += res.total_tokens_saved_by_rcs
            except Exception as e:
                logger.error("Pipeline member '%s' failed: %s", name, e)
                return AgentGroupResult(
                    session_id=self._root_session_id(),
                    group_name=self.config.name,
                    member_results=member_results,
                    status="failed",
                    error=str(e),
                    duration_ms=int((time.time() - start_time) * 1000),
                )

        return AgentGroupResult(
            session_id=self._root_session_id(),
            group_name=self.config.name,
            final_response=current_input,
            member_results=member_results,
            turns_used=turns_used,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=total_tokens_saved,
            duration_ms=int((time.time() - start_time) * 1000),
            status="completed",
        )

    async def _run_pipeline_stream(
        self, user_message: str
    ) -> AsyncIterator[AgentStreamEvent]:
        """Streaming pipeline: forward member events; expose last member output."""
        start_time = time.time()
        current_input = user_message
        member_results: dict[str, Any] = {}
        turns_used = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_tokens_saved = 0
        final_response: Optional[str] = None
        status = "completed"
        error_msg: Optional[str] = None

        for name, member in self._members.items():
            logger.info("Pipeline stream: Executing member '%s'", name)
            yield AgentStreamEvent(
                event_type="event",
                content=f"Pipeline member '{name}' started.",
                data={"group": self.config.name, "member": name},
            )

            try:
                if isinstance(member, AgentRunner):
                    async for event in member.run_stream(current_input, stream=True):
                        yield self._tag_member_event(name, event)
                        if event.event_type == "final_response" and event.data:
                            member_results[name] = AgentRunResult(**event.data)
                            current_input = event.content or ""
                            final_response = event.content
                            turns_used += event.data.get("turns_used", 0)
                            total_tokens_in += event.data.get("total_tokens_in", 0)
                            total_tokens_out += event.data.get("total_tokens_out", 0)
                            total_tokens_saved += event.data.get("total_tokens_saved_by_rcs", 0)
                elif isinstance(member, AgentOrchestrator):
                    async for event in member.run_stream(current_input, stream=True):
                        yield self._tag_member_event(name, event)
                        if event.event_type == "final_response" and event.data:
                            member_results[name] = event.data
                            current_input = event.content or ""
                            final_response = event.content
                            turns_used += event.data.get("turns_used", 0)
                            total_tokens_in += event.data.get("total_tokens_in", 0)
                            total_tokens_out += event.data.get("total_tokens_out", 0)
                            total_tokens_saved += event.data.get("total_tokens_saved_by_rcs", 0)
            except Exception as e:
                logger.error("Pipeline member '%s' failed: %s", name, e)
                status = "failed"
                error_msg = str(e)
                yield AgentStreamEvent(
                    event_type="error",
                    content=error_msg,
                    data={"group": self.config.name, "member": name, "status": "failed"},
                )
                break

        group_result = AgentGroupResult(
            session_id=self._root_session_id(),
            group_name=self.config.name,
            final_response=final_response,
            member_results=member_results,
            turns_used=turns_used,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=total_tokens_saved,
            duration_ms=int((time.time() - start_time) * 1000),
            status=status,
            error=error_msg,
        )

        yield AgentStreamEvent(
            event_type="final_response",
            content=final_response,
            data=group_result.model_dump(),
        )

    def _aggregate_parallel(
        self, member_results: dict[str, Any], ordered_names: list[str]
    ) -> Optional[str]:
        """Combine parallel member outputs per the group's aggregation strategy."""
        responses = [
            (name, getattr(member_results.get(name), "final_response", None))
            for name in ordered_names
        ]
        responses = [(n, r) for n, r in responses if r]
        if not responses:
            return None
        if self.config.aggregation_strategy == "first_complete":
            return responses[0][1]
        # Default: concatenate labeled member outputs.
        return "\n\n".join(f"[{name}]\n{resp}" for name, resp in responses)

    async def _run_parallel(
        self,
        user_message: str,
        start_time: float,
    ) -> AgentGroupResult:
        """Parallel pattern: run all members concurrently on the same input."""
        names = list(self._members.keys())

        async def run_member(name: str, member: Any) -> tuple[str, Any]:
            res = await member.run(user_message, stream=False)
            return name, res

        gathered = await asyncio.gather(
            *(run_member(n, m) for n, m in self._members.items()),
            return_exceptions=True,
        )

        member_results: dict[str, Any] = {}
        turns_used = total_tokens_in = total_tokens_out = total_tokens_saved = 0
        for item in gathered:
            if isinstance(item, Exception):
                logger.error("Parallel member failed: %s", item)
                return AgentGroupResult(
                    session_id=self._root_session_id(),
                    group_name=self.config.name,
                    member_results=member_results,
                    status="failed",
                    error=str(item),
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            name, res = item
            member_results[name] = res
            turns_used += res.turns_used
            total_tokens_in += res.total_tokens_in
            total_tokens_out += res.total_tokens_out
            total_tokens_saved += res.total_tokens_saved_by_rcs

        return AgentGroupResult(
            session_id=self._root_session_id(),
            group_name=self.config.name,
            final_response=self._aggregate_parallel(member_results, names),
            member_results=member_results,
            turns_used=turns_used,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=total_tokens_saved,
            duration_ms=int((time.time() - start_time) * 1000),
            status="completed",
        )

    async def _run_parallel_stream(
        self, user_message: str
    ) -> AsyncIterator[AgentStreamEvent]:
        """Streaming parallel: multiplex member event streams concurrently."""
        start_time = time.time()
        names = list(self._members.keys())
        queue: asyncio.Queue = asyncio.Queue()
        member_results: dict[str, Any] = {}
        _DONE = object()

        async def pump(name: str, member: Any) -> None:
            try:
                async for event in member.run_stream(user_message, stream=True):
                    await queue.put((name, event))
            except Exception as exc:  # pragma: no cover - member failure
                await queue.put((
                    name,
                    AgentStreamEvent(
                        event_type="error",
                        content=str(exc),
                        data={"member": name, "status": "failed"},
                    ),
                ))
            finally:
                await queue.put((name, _DONE))

        tasks = [asyncio.create_task(pump(n, m)) for n, m in self._members.items()]
        remaining = len(tasks)
        turns_used = total_tokens_in = total_tokens_out = total_tokens_saved = 0

        while remaining > 0:
            name, event = await queue.get()
            if event is _DONE:
                remaining -= 1
                continue
            yield self._tag_member_event(name, event)
            if event.event_type == "final_response" and event.data:
                member_results[name] = AgentRunResult(**event.data)
                turns_used += event.data.get("turns_used", 0)
                total_tokens_in += event.data.get("total_tokens_in", 0)
                total_tokens_out += event.data.get("total_tokens_out", 0)
                total_tokens_saved += event.data.get("total_tokens_saved_by_rcs", 0)

        for task in tasks:
            if not task.done():
                task.cancel()

        group_result = AgentGroupResult(
            session_id=self._root_session_id(),
            group_name=self.config.name,
            final_response=self._aggregate_parallel(member_results, names),
            member_results=member_results,
            turns_used=turns_used,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=total_tokens_saved,
            duration_ms=int((time.time() - start_time) * 1000),
            status="completed",
        )

        yield AgentStreamEvent(
            event_type="final_response",
            content=group_result.final_response,
            data=group_result.model_dump(),
        )

    async def _run_supervisor(
        self,
        user_message: str,
        start_time: float,
        *,
        stream: bool,
    ) -> AgentGroupResult:
        """Supervisor pattern: designated agent delegates subtasks via member tools."""
        supervisor_name = None
        for name in self._members.keys():
            if name == "supervisor" or "supervisor" in name.lower():
                supervisor_name = name
                break

        if not supervisor_name and self._members:
            supervisor_name = list(self._members.keys())[0]

        if not supervisor_name:
            return AgentGroupResult(
                session_id=self._root_session_id(),
                group_name=self.config.name,
                status="failed",
                error="No members available in supervisor group",
                duration_ms=int((time.time() - start_time) * 1000),
            )

        supervisor = self._members[supervisor_name]
        if not isinstance(supervisor, AgentRunner):
            return AgentGroupResult(
                session_id=self._root_session_id(),
                group_name=self.config.name,
                status="failed",
                error="Supervisor member must be a single AgentRunner",
                duration_ms=int((time.time() - start_time) * 1000),
            )

        member_results: dict[str, Any] = {}
        turns_used = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_tokens_saved = 0

        def _make_delegate_tool(member_name: str, member_obj: Any):
            """Build a delegate tool whose signature exposes only ``task_input``.

            ``member_name``/``member_obj`` are captured in the closure (not as
            default parameter values) so they are not surfaced to the LLM as
            tool parameters and do not break JSON-schema generation.
            """
            async def call_member_tool(task_input: str) -> str:
                logger.info(
                    "Supervisor calling subtask agent '%s' with input: %s",
                    member_name,
                    task_input[:100],
                )
                if isinstance(member_obj, AgentRunner):
                    sub_res = await member_obj.run(task_input, stream=False)
                    member_results[member_name] = sub_res
                    nonlocal turns_used, total_tokens_in, total_tokens_out, total_tokens_saved
                    turns_used += sub_res.turns_used
                    total_tokens_in += sub_res.total_tokens_in
                    total_tokens_out += sub_res.total_tokens_out
                    total_tokens_saved += sub_res.total_tokens_saved_by_rcs
                    return sub_res.final_response or "Completed with no output."
                elif isinstance(member_obj, AgentOrchestrator):
                    sub_res = await member_obj.run(task_input, stream=False)
                    member_results[member_name] = sub_res
                    turns_used += sub_res.turns_used
                    total_tokens_in += sub_res.total_tokens_in
                    total_tokens_out += sub_res.total_tokens_out
                    total_tokens_saved += sub_res.total_tokens_saved_by_rcs
                    return sub_res.final_response or "Completed with no output."
                return "Failed to run sub-agent."

            call_member_tool._nexus_tool = True
            call_member_tool._tool_name = f"delegate_to_{member_name}"
            call_member_tool._tool_description = (
                f"Delegate a sub-task to the specialized helper agent named {member_name}. "
                "Input is the request details."
            )
            call_member_tool._tool_tags = ["multiagent", "delegate"]
            call_member_tool._tool_requires_approval = False
            call_member_tool._tool_timeout_seconds = 60
            return call_member_tool

        for name, member in self._members.items():
            if name == supervisor_name:
                continue
            self.tool_registry.register_tool(
                _make_delegate_tool(name, member), plugin_name="supervisor"
            )

        try:
            logger.info(
                "Supervisor: Starting execution with supervisor agent '%s'",
                supervisor_name,
            )
            supervisor_res = await supervisor.run(user_message, stream=False)
            member_results[supervisor_name] = supervisor_res
            turns_used += supervisor_res.turns_used
            total_tokens_in += supervisor_res.total_tokens_in
            total_tokens_out += supervisor_res.total_tokens_out
            total_tokens_saved += supervisor_res.total_tokens_saved_by_rcs
        except Exception as e:
            logger.error("Supervisor agent failed: %s", e)
            return AgentGroupResult(
                session_id=self._root_session_id(),
                group_name=self.config.name,
                member_results=member_results,
                status="failed",
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

        return AgentGroupResult(
            session_id=self._root_session_id(),
            group_name=self.config.name,
            final_response=supervisor_res.final_response,
            member_results=member_results,
            turns_used=turns_used,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=total_tokens_saved,
            duration_ms=int((time.time() - start_time) * 1000),
            status="completed",
        )

    async def _run_supervisor_stream(
        self, user_message: str
    ) -> AsyncIterator[AgentStreamEvent]:
        """Streaming supervisor: stream supervisor agent events; sub-agents run blocking."""
        start_time = time.time()
        supervisor_name = None
        for name in self._members.keys():
            if name == "supervisor" or "supervisor" in name.lower():
                supervisor_name = name
                break
        if not supervisor_name and self._members:
            supervisor_name = list(self._members.keys())[0]

        if not supervisor_name:
            yield AgentStreamEvent(
                event_type="error",
                content="No members available in supervisor group",
                data={"group": self.config.name, "status": "failed"},
            )
            return

        supervisor = self._members[supervisor_name]
        if not isinstance(supervisor, AgentRunner):
            yield AgentStreamEvent(
                event_type="error",
                content="Supervisor member must be a single AgentRunner",
                data={"group": self.config.name, "status": "failed"},
            )
            return

        member_results: dict[str, Any] = {}
        turns_used = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_tokens_saved = 0
        final_response: Optional[str] = None
        status = "completed"
        error_msg: Optional[str] = None

        def _make_delegate_tool(member_name: str, member_obj: Any):
            """Build a delegate tool whose signature exposes only ``task_input``.

            See the non-streaming supervisor for rationale: capturing
            ``member_name``/``member_obj`` in the closure (not as default
            parameter values) keeps them out of the LLM-visible schema and
            avoids non-serializable-default JSON-schema warnings.
            """
            async def call_member_tool(task_input: str) -> str:
                if isinstance(member_obj, AgentRunner):
                    sub_res = await member_obj.run(task_input, stream=False)
                    member_results[member_name] = sub_res
                    nonlocal turns_used, total_tokens_in, total_tokens_out, total_tokens_saved
                    turns_used += sub_res.turns_used
                    total_tokens_in += sub_res.total_tokens_in
                    total_tokens_out += sub_res.total_tokens_out
                    total_tokens_saved += sub_res.total_tokens_saved_by_rcs
                    return sub_res.final_response or "Completed with no output."
                elif isinstance(member_obj, AgentOrchestrator):
                    sub_res = await member_obj.run(task_input, stream=False)
                    member_results[member_name] = sub_res
                    turns_used += sub_res.turns_used
                    total_tokens_in += sub_res.total_tokens_in
                    total_tokens_out += sub_res.total_tokens_out
                    total_tokens_saved += sub_res.total_tokens_saved_by_rcs
                    return sub_res.final_response or "Completed with no output."
                return "Failed to run sub-agent."

            call_member_tool._nexus_tool = True
            call_member_tool._tool_name = f"delegate_to_{member_name}"
            call_member_tool._tool_description = (
                f"Delegate a sub-task to the specialized helper agent named {member_name}."
            )
            call_member_tool._tool_tags = ["multiagent", "delegate"]
            call_member_tool._tool_requires_approval = False
            call_member_tool._tool_timeout_seconds = 60
            return call_member_tool

        for name, member in self._members.items():
            if name == supervisor_name:
                continue
            self.tool_registry.register_tool(
                _make_delegate_tool(name, member), plugin_name="supervisor"
            )

        try:
            async for event in supervisor.run_stream(user_message, stream=True):
                yield self._tag_member_event(supervisor_name, event)
                if event.event_type == "final_response" and event.data:
                    member_results[supervisor_name] = AgentRunResult(**event.data)
                    final_response = event.content
                    turns_used += event.data.get("turns_used", 0)
                    total_tokens_in += event.data.get("total_tokens_in", 0)
                    total_tokens_out += event.data.get("total_tokens_out", 0)
                    total_tokens_saved += event.data.get("total_tokens_saved_by_rcs", 0)
        except Exception as e:
            logger.error("Supervisor agent failed: %s", e)
            status = "failed"
            error_msg = str(e)
            yield AgentStreamEvent(
                event_type="error",
                content=error_msg,
                data={"group": self.config.name, "member": supervisor_name, "status": "failed"},
            )

        group_result = AgentGroupResult(
            session_id=self._root_session_id(),
            group_name=self.config.name,
            final_response=final_response,
            member_results=member_results,
            turns_used=turns_used,
            total_tokens_in=total_tokens_in,
            total_tokens_out=total_tokens_out,
            total_tokens_saved_by_rcs=total_tokens_saved,
            duration_ms=int((time.time() - start_time) * 1000),
            status=status,
            error=error_msg,
        )

        yield AgentStreamEvent(
            event_type="final_response",
            content=final_response,
            data=group_result.model_dump(),
        )
