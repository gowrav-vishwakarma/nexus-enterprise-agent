#!/usr/bin/env python3
"""Annotated orchestration runner — every OrchestrationRuntime parameter explained.

This is a reference copy for learning. The runnable example is examples/orchestration/run_team.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from nexus import OrchestrationManifest, OrchestrationRuntime, RunContext

# Optional: build a ToolRegistry in code and pass it to from_manifest(). This is
# the modern path: define flat @tool functions, group them with add_toolset(),
# and select packs in YAML via `agents.<name>.toolset:`.
# from nexus import ToolRegistry
# from nexus.tools.decorators import tool
# @tool(name="web_search")
# def web_search(query: str) -> str:
#     return f"Results for {query}"
# registry = ToolRegistry()
# registry.add_toolset("researcher", [web_search])
# tool_registry = registry

# Optional: override storage per tenant in SaaS apps.
# from nexus.persistence import PersistenceResolver
# persistence_resolver = MyTenantResolver()


async def main() -> None:
    manifest_path = Path("examples/orchestration/research_team.yaml")

    # Load YAML + companion prompts module once (safe to cache in production).
    manifest = OrchestrationManifest.load(manifest_path)

    # Chat thread id — use a stable id to continue the same conversation.
    session_id = str(uuid4())

    # OrchestrationRuntime.from_manifest — builds AgentRunner or AgentOrchestrator from manifest.
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        # run_context (required) — who is calling and which chat thread.
        run_context=RunContext(
            tenant_id="demo-tenant",   # optional, default: None — which customer/org
            user_id="demo-user",       # optional, default: None — scopes chat history + cross-session user_memory (tenant + user)
            session_id=session_id,     # optional, default: None — chat thread id; set BEFORE runtime for teams
            request_id=None,           # optional, default: None — your tracing/correlation id
            metadata={},               # optional, default: {} — extra key/value bag for tools
        ),
        # tool_registry (optional, default: None)
        # Pre-built registry from add_tool() / add_toolset(). YAML plugins: still
        # loaded and registered on top when plugins: is non-empty.
        tool_registry=None,
        # persistence_resolver (optional, default: None)
        # Override manifest storage per tenant/user (SaaS pattern).
        persistence_resolver=None,
        # event_emitter (optional, default: None)
        # Hook for structured observability events (single-agent root only).
        event_emitter=None,
        # cross_session_enabled (optional, default: True)
        # When True, builds a cross-chat memory store from manifest storage settings.
        cross_session_enabled=True,
    )

    # run(user_message) — blocking; returns AgentRunResult or AgentGroupResult.
    result = await runtime.run("Summarize recent framework releases.")
    print(result.final_response)
    print(f"session_id={session_id}")

    # Streaming alternative (optional):
    # async for event in runtime.run_stream("Hello", stream=True):
    #     if event.event_type == "content":
    #         print(event.content, end="", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
