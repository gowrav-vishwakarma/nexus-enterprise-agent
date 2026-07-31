#!/usr/bin/env python3
"""Annotated single-agent Python API — every AgentConfig and AgentRunner parameter explained.

This is a reference copy for learning. Copy patterns into your own app.
"""

from __future__ import annotations

import asyncio
import os

from pydantic import SecretStr

from nexus.config.agent import AgentConfig, AgentPersonaConfig, TurnConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.context_summary import ContextSummaryConfig
from nexus.config.memory import MemoryConfig
from nexus.config.rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from nexus.config.storage import SessionStorageConfig
from nexus.memory import SQLiteCrossSessionMemoryStore
from nexus.runner.agent_runner import AgentRunner
from nexus.skills.config import SkillsConfig
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(name="echo", description="Echo back the input text")
def echo(text: str) -> str:
    """Echo back the input."""
    return text


def build_agent_config() -> AgentConfig:
    """AgentConfig — describes what the agent is."""
    return AgentConfig(
        # name (required) — unique id for this agent; used in logs and saved sessions.
        name="assistant",
        # llm (required) — which large language model (LLM) to call.
        llm=LLMProviderConfig(
            provider="openai",                          # optional, default: openai
            model="gpt-4o-mini",                        # optional, default: gpt-4o
            api_key=SecretStr(os.environ.get("OPENAI_API_KEY", "sk-...")),
            base_url=None,                              # optional, default: None — custom endpoint URL
            api_version=None,                           # optional, default: None
            context_window_tokens=128000,               # optional, default: 128000
            timeout=60,                                 # optional, default: 60 seconds
            max_retries=3,                              # optional, default: 3
            retry_delay=1.0,                            # optional, default: 1.0 seconds
            extra_headers={},                           # optional, default: {}
            default_params={},                          # optional, default: {}
        ),
        # persona (optional) — how the agent describes itself in the system prompt.
        persona=AgentPersonaConfig(
            role="Helpful assistant",                   # required in persona block
            goal="Answer clearly and use tools when useful.",
            backstory=None,                             # optional, default: None
            system_prompt=None,                         # optional, default: None — full override
            # system_prompt_template uses framework default Jinja template if omitted
        ),
        # turns (optional) — limits on the agent loop.
        turns=TurnConfig(
            max_turns=10,                               # optional, default: 10
            max_tool_calls_per_turn=5,                  # optional, default: 5 (0 = unlimited)
            stop_on_empty_tool_calls=True,              # optional, default: True
            stop_sequences=[],                          # optional, default: []
            stop_on_result_type=True,                   # optional, default: True
            human_in_loop_after_turns=None,             # optional, default: None
            turn_timeout_seconds=300,                   # optional, default: 300
        ),
        # rcs (optional) — Runtime Context Summarization; compresses long tool outputs.
        rcs=RuntimeContextSummarizerConfig(
            enabled=False,                              # optional, default: False
            tc_tag_format="[TC{n}]",                   # optional, default: "[TC{n}]"
            tc_tag_include_tool_signature=True,         # optional, default: True
            context_updates_param_name="_context_updates",  # optional, default: "_context_updates"
            fallback_compactor=ServerCompactorConfig(
                enabled=False,                          # optional, default: False
                trigger_token_threshold=10000,          # optional, default: 10000
                compact_oldest_n_tcs=2,                 # optional, default: 2
                max_tokens_per_summary=100,             # optional, default: 100
            ),
        ),
        # memory (optional) — durable user facts across chat threads.
        memory=MemoryConfig(
            enabled=False,                              # optional, default: False
            namespace="",                               # optional, default: "" (uses agent name)
            max_entities=100,                           # optional, default: 100
            extract_after_each_turn=True,               # optional, default: True
            inject_into_prompt=True,                    # optional, default: True
            max_conversation_chars=6000,                # optional, default: 6000
        ),
        # context_summary (optional) — fold oldest turns into summary_text when window fills.
        context_summary=ContextSummaryConfig(
            summarize_on=None,                          # optional, default: None (disabled); e.g. 0.8 = 80%
            turns_to_fold=2,                            # optional, default: 2
            max_summary_chars=4000,                     # optional, default: 4000
            inject_into_prompt=True,                    # optional, default: True
        ),
        # storage (optional, default: None) — fallback when runner has no storage_config.
        storage=None,
        # toolset (optional, default: None) — name of a toolset defined on the registry;
        # None means every registered tool is visible. Use instead of (or alongside)
        # tool_plugins when you register flat tools via add_toolset().
        toolset=None,
        # tool_plugins (optional, default: []) — legacy allow-list of plugin namespaces.
        tool_plugins=[],
        # skills (optional) — agentskills.io SKILL.md folders.
        skills=SkillsConfig(
            enabled=False,                              # optional, default: False
            activation_mode="auto",                     # optional, default: "auto"
            allow_scripts=False,                        # optional, default: False
        ),
        result_type=None,                               # optional, default: None — Pydantic structured output
        trace_enabled=False,                            # optional, default: False
        trace_sink="stdout",                            # optional, default: "stdout" | "otel"
        stream_output=False,                            # optional, default: False — blocking vs streaming
        metadata={},                                    # optional, default: {}
    )


async def main() -> None:
    config = build_agent_config()

    # ToolRegistry (required) — catalog of tools the LLM can call.
    registry = ToolRegistry()
    registry.add_tool(echo)  # flat name "echo" (no plugin prefix)

    # AgentRunner — executes the agent loop.
    runner = AgentRunner(
        config=config,                                      # required
        tool_registry=registry,                             # required
        storage_config=SessionStorageConfig(
            adapter="sqlite",                               # optional, default on runner: in-memory
            adapter_config={"tenant_scoped": True},         # uses NEXUS_DATA_ROOT (default ./tenants)
        ),
        run_context=RunContext(
            tenant_id="demo",                               # optional, default: empty RunContext
            user_id="demo-user",                            # scopes chat history + cross-session user_memory (tenant + user)
            session_id="sess-1",
            metadata={},
        ),
        event_emitter=None,                                 # optional, default: new NexusEventEmitter
        cross_session_memory_store=SQLiteCrossSessionMemoryStore(),  # optional; needed if memory.enabled
        on_turn_end=None,                                   # optional; TurnDecision hook after each turn
    )

    # run() — blocking execution; returns AgentRunResult.
    result = await runner.run(
        user_message="Echo hello",                          # required
        session_id=None,                                    # optional — override chat id for this call only
        initial_context={"deal_id": "D-99"},                # optional — merged into session metadata once
        stream=None,                                        # optional — None uses config.stream_output
    )
    print(result.final_response)
    print("turns:", result.turns_used)


if __name__ == "__main__":
    asyncio.run(main())
