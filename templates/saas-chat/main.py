"""SaaS chat API starter — multi-tenant HTTP agent with traces that stay clean.

Run it:

    export OPENAI_API_KEY=sk-...
    uv run uvicorn templates.saas-chat.main:app --reload

Then:

    curl -X POST localhost:8000/v1/chat \
      -H 'x-tenant-id: acme' -H 'x-user-id: u1' \
      -H 'content-type: application/json' -d '{"message": "hello"}'

Every request builds its own `RunContext`, and sessions, memory, and buffered
streams are partitioned by it. See docs/reference/serve.md.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request

from nexus.config.agent import AgentConfig, AgentPersonaConfig, TurnConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.storage import SessionStorageConfig
from nexus.events.emitter import RedactingEventSink, StdoutEventSink
from nexus.guardrails.audit import AuditSink
from nexus.runner.agent_runner import AgentRunner
from nexus.serve import AgentRouterConfig, create_agent_router
from nexus.serve.replay import StreamReplayBuffer
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

DATA_ROOT = os.getenv("NEXUS_DATA_ROOT", "./tenants")


async def context_factory(request: Request) -> RunContext:
    """Derive the tenant boundary from the request.

    Replace the headers with your real auth: decode the bearer token and read the
    tenant and user from its claims. Everything downstream is scoped by what this
    returns, so never default the tenant.
    """
    tenant_id = request.headers.get("x-tenant-id")
    user_id = request.headers.get("x-user-id")
    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Missing tenant or user")
    return RunContext(
        tenant_id=tenant_id,
        company_id=request.headers.get("x-company-id"),
        user_id=user_id,
        should_persist=True,
    )


async def runner_factory(ctx: RunContext) -> AgentRunner:
    config = AgentConfig(
        name="saas-chat",
        llm=LLMProviderConfig(
            provider="openai",
            model=os.getenv("AGENT_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
        ),
        persona=AgentPersonaConfig(
            role="a helpful product assistant",
            goal="Answer questions about the product accurately",
        ),
        turns=TurnConfig(max_turns=10),
        storage=SessionStorageConfig(
            adapter="sqlite",
            adapter_config={"data_root": DATA_ROOT, "tenant_scoped": True},
        ),
    )
    runner = AgentRunner(
        config=config,
        tool_registry=ToolRegistry(),
        run_context=ctx,
    )
    # Traces leave the tenant boundary, so strip PII and secrets on the way out,
    # and keep a scope-keyed record of what ran.
    runner.event_emitter.register_sink(RedactingEventSink(StdoutEventSink()))
    runner.event_emitter.register_sink(AuditSink(ctx=ctx))
    return runner


app = FastAPI(title="Nexus SaaS chat starter")
app.include_router(
    create_agent_router(
        runner_factory,
        context_factory,
        config=AgentRouterConfig(prefix="/v1"),
        # Survives a dropped browser connection without re-running the agent.
        replay_buffer=StreamReplayBuffer(max_events_per_session=1000, ttl_seconds=900),
    )
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
