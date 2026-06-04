"""Agent orchestrator for executing multi-agent patterns."""

import asyncio
import logging
import time
from typing import Any, Optional, Union

from nexus.config.agent import AgentConfig, AgentGroupConfig
from nexus.multiagent.results import AgentGroupResult
from nexus.runner.agent_runner import AgentRunner
from nexus.runner.result import AgentRunResult
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
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
        user_memory_store: Optional[Any] = None,
    ):
        self.config = config
        self.tool_registry = tool_registry or ToolRegistry()
        self.storage_config = storage_config
        self.run_context = run_context or RunContext()
        self.user_memory_store = user_memory_store
        self._init_members()

    def _init_members(self) -> None:
        """Initialize runners/orchestrators for all group members recursively."""
        self._members: dict[str, Union[AgentRunner, "AgentOrchestrator"]] = {}
        
        for member in self.config.members:
            # Generate member session ID prefix/postfix
            m_ctx = RunContext(
                tenant_id=self.run_context.tenant_id,
                user_id=self.run_context.user_id,
                session_id=f"{self.config.session_id_prefix}{self.run_context.session_id}_{member.name}" if self.run_context.session_id else None,
            )

            if isinstance(member, AgentConfig):
                # Create runner for AgentConfig
                runner = AgentRunner(
                    config=member,
                    tool_registry=self.tool_registry,
                    storage_config=self.storage_config,
                    run_context=m_ctx,
                    user_memory_store=self.user_memory_store,
                )
                self._members[member.name] = runner
            elif isinstance(member, AgentGroupConfig):
                # Create nested orchestrator
                nested_orc = AgentOrchestrator(
                    config=member,
                    tool_registry=self.tool_registry,
                    storage_config=self.storage_config,
                    run_context=m_ctx,
                    user_memory_store=self.user_memory_store,
                )
                self._members[member.name] = nested_orc

    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> AgentGroupResult:
        """Execute the multi-agent group pattern recursively."""
        start_time = time.time()
        
        # Sync session ID across orchestrator context
        if session_id:
            self.run_context.session_id = session_id

        if self.config.pattern == "pipeline":
            return await self._run_pipeline(user_message, start_time)
        elif self.config.pattern == "supervisor":
            return await self._run_supervisor(user_message, start_time)
        else:
            # Fallback for swarm/parallel: execute sequentially for now
            return await self._run_pipeline(user_message, start_time)

    async def _run_pipeline(self, user_message: str, start_time: float) -> AgentGroupResult:
        """Pipeline pattern: output of member N becomes input to member N+1."""
        current_input = user_message
        member_results = {}
        turns_used = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_tokens_saved = 0

        for name, member in self._members.items():
            logger.info("Pipeline: Executing member '%s'", name)
            
            try:
                if isinstance(member, AgentRunner):
                    res = await member.run(current_input)
                    member_results[name] = res
                    current_input = res.final_response or ""
                    turns_used += res.turns_used
                    total_tokens_in += res.total_tokens_in
                    total_tokens_out += res.total_tokens_out
                    total_tokens_saved += res.total_tokens_saved_by_rcs
                elif isinstance(member, AgentOrchestrator):
                    res = await member.run(current_input)
                    member_results[name] = res
                    current_input = res.final_response or ""
                    turns_used += res.turns_used
                    total_tokens_in += res.total_tokens_in
                    total_tokens_out += res.total_tokens_out
                    total_tokens_saved += res.total_tokens_saved_by_rcs
            except Exception as e:
                logger.error("Pipeline member '%s' failed: %s", name, e)
                return AgentGroupResult(
                    group_name=self.config.name,
                    member_results=member_results,
                    status="failed",
                    error=str(e),
                    duration_ms=int((time.time() - start_time) * 1000),
                )

        return AgentGroupResult(
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

    async def _run_supervisor(self, user_message: str, start_time: float) -> AgentGroupResult:
        """Supervisor pattern: Designated agent delegates subtasks sequentially via member tools."""
        # Find supervisor runner in member list
        supervisor_name = None
        for name in self._members.keys():
            if name == "supervisor" or "supervisor" in name.lower():
                supervisor_name = name
                break
        
        # Fallback to the first member as supervisor
        if not supervisor_name and self._members:
            supervisor_name = list(self._members.keys())[0]

        if not supervisor_name:
            return AgentGroupResult(
                group_name=self.config.name,
                status="failed",
                error="No members available in supervisor group",
                duration_ms=int((time.time() - start_time) * 1000),
            )

        supervisor = self._members[supervisor_name]
        if not isinstance(supervisor, AgentRunner):
            return AgentGroupResult(
                group_name=self.config.name,
                status="failed",
                error="Supervisor member must be a single AgentRunner",
                duration_ms=int((time.time() - start_time) * 1000),
            )

        member_results = {}
        turns_used = 0
        total_tokens_in = 0
        total_tokens_out = 0
        total_tokens_saved = 0

        # Define dynamic tools for all OTHER members so the supervisor can invoke them
        for name, member in self._members.items():
            if name == supervisor_name:
                continue

            # We define an async callable function to expose as a tool
            async def call_member_tool(task_input: str, member_name: str = name, member_obj: Any = member) -> str:
                """Execute subtask using a helper agent."""
                logger.info("Supervisor calling subtask agent '%s' with input: %s", member_name, task_input[:100])
                if isinstance(member_obj, AgentRunner):
                    sub_res = await member_obj.run(task_input)
                    member_results[member_name] = sub_res
                    nonlocal turns_used, total_tokens_in, total_tokens_out, total_tokens_saved
                    turns_used += sub_res.turns_used
                    total_tokens_in += sub_res.total_tokens_in
                    total_tokens_out += sub_res.total_tokens_out
                    total_tokens_saved += sub_res.total_tokens_saved_by_rcs
                    return sub_res.final_response or "Completed with no output."
                elif isinstance(member_obj, AgentOrchestrator):
                    sub_res = await member_obj.run(task_input)
                    member_results[member_name] = sub_res
                    turns_used += sub_res.turns_used
                    total_tokens_in += sub_res.total_tokens_in
                    total_tokens_out += sub_res.total_tokens_out
                    total_tokens_saved += sub_res.total_tokens_saved_by_rcs
                    return sub_res.final_response or "Completed with no output."
                return "Failed to run sub-agent."

            # Set tool attributes to be scanned by register_tool
            call_member_tool._nexus_tool = True
            call_member_tool._tool_name = f"delegate_to_{name}"
            call_member_tool._tool_description = f"Delegate a sub-task to the specialized helper agent named {name}. Input is the request details."
            call_member_tool._tool_tags = ["multiagent", "delegate"]
            call_member_tool._tool_requires_approval = False
            call_member_tool._tool_timeout_seconds = 60

            # Register directly in the supervisor's registry (which may be shared or private)
            self.tool_registry.register_tool(call_member_tool, plugin_name="supervisor")

        # Run supervisor
        try:
            logger.info("Supervisor: Starting execution with supervisor agent '%s'", supervisor_name)
            supervisor_res = await supervisor.run(user_message)
            member_results[supervisor_name] = supervisor_res
            turns_used += supervisor_res.turns_used
            total_tokens_in += supervisor_res.total_tokens_in
            total_tokens_out += supervisor_res.total_tokens_out
            total_tokens_saved += supervisor_res.total_tokens_saved_by_rcs
        except Exception as e:
            logger.error("Supervisor agent failed: %s", e)
            return AgentGroupResult(
                group_name=self.config.name,
                member_results=member_results,
                status="failed",
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )

        return AgentGroupResult(
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
