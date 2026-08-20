"""FastAPI router factory for chat, stream, resume, and sessions.

This module deliberately avoids ``from __future__ import annotations``: FastAPI
resolves endpoint annotations with ``get_type_hints``, which cannot see the
request/body types defined inside ``create_agent_router`` once they are strings.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from nexus.runner.agent_runner import AgentRunner
from nexus.runner.result import AgentRunResult
from nexus.scope import ScopeLevel, scope_key
from nexus.serve.replay import StreamReplayBuffer, buffered_stream
from nexus.tools.context import RunContext

RunContextFactory = Callable[..., Awaitable[RunContext]]
RunnerFactory = Callable[[RunContext], Awaitable[AgentRunner]]


@dataclass
class AgentRouterConfig:
    prefix: str = "/v1"
    require_auth: bool = False


def _replay_key(ctx: RunContext, session_id: str) -> str:
    """Scope the buffer so one tenant can never reattach to another's stream."""
    return f"{scope_key(ctx, ScopeLevel.USER)}:{session_id}"


def create_agent_router(
    runner_factory: RunnerFactory,
    context_factory: RunContextFactory,
    *,
    config: Optional[AgentRouterConfig] = None,
    replay_buffer: Optional[StreamReplayBuffer] = None,
) -> Any:
    """Return a FastAPI APIRouter with chat, stream, resume, and session endpoints."""
    try:
        import json

        from fastapi import APIRouter, HTTPException, Request
        from fastapi.responses import StreamingResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for nexus.serve. Install with: pip install nexus-enterprise-agent[serve]"
        ) from exc

    cfg = config or AgentRouterConfig()
    router = APIRouter(prefix=cfg.prefix, tags=["nexus-agent"])
    buffer = replay_buffer if replay_buffer is not None else StreamReplayBuffer()

    def _ensure_identity(ctx: RunContext) -> None:
        """When require_auth is on, the context must name who is calling."""
        if not cfg.require_auth:
            return
        if ctx.tenant_id or ctx.company_id or ctx.user_id:
            return
        raise HTTPException(status_code=401, detail="Authentication required")

    def _sse(seq: int, payload: dict[str, Any]) -> str:
        # The id: line is what the browser sends back as Last-Event-ID.
        return f"id: {seq}\ndata: {json.dumps(payload)}\n\n"

    def _last_seq(request: Request) -> int:
        raw = request.headers.get("last-event-id") or request.query_params.get("last_seq")
        try:
            return int(raw) if raw is not None else 0
        except ValueError:
            return 0

    class ChatRequest(BaseModel):
        message: str
        session_id: Optional[str] = None

    class ResumeRequest(BaseModel):
        results: list[dict[str, Any]] = Field(default_factory=list)

    @router.post("/chat")
    async def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
        ctx = await context_factory(request)
        _ensure_identity(ctx)
        if body.session_id:
            ctx.session_id = body.session_id
        runner = await runner_factory(ctx)
        result: AgentRunResult = await runner.run(
            body.message, session_id=ctx.session_id, stream=False
        )
        return result.model_dump()

    @router.post("/chat/stream")
    async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
        ctx = await context_factory(request)
        _ensure_identity(ctx)
        if body.session_id:
            ctx.session_id = body.session_id
        runner = await runner_factory(ctx)
        key = _replay_key(ctx, ctx.session_id or "")

        async def event_generator():
            events = runner.run_stream(body.message, session_id=ctx.session_id, stream=True)
            async for seq, payload in buffered_stream(events, buffer, key):
                yield _sse(seq, payload)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @router.get("/sessions/{session_id}/stream")
    async def reattach_stream(session_id: str, request: Request) -> StreamingResponse:
        """Rejoin a stream after a dropped connection, without re-running the agent.

        Send the last sequence number you received as the `Last-Event-ID` header
        (browsers do this automatically for `EventSource`) or a `last_seq` query
        parameter. Buffered events after that point are replayed, then the stream
        follows the run until it finishes.
        """
        ctx = await context_factory(request)
        _ensure_identity(ctx)
        ctx.session_id = session_id
        key = _replay_key(ctx, session_id)
        if not buffer.has(key):
            raise HTTPException(status_code=404, detail="No replayable stream for session")

        after = _last_seq(request)
        earliest = buffer.earliest_seq(key)
        if earliest is not None and after and after + 1 < earliest:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Events after {after} are no longer buffered "
                    f"(earliest retained is {earliest}); reload the session instead"
                ),
            )

        async def event_generator():
            async for payload in buffer.replay(key, after_seq=after):
                seq = (payload.get("data") or {}).get("seq", 0)
                yield _sse(seq, payload)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @router.post("/sessions/{session_id}/resume")
    async def resume_session(
        session_id: str, body: ResumeRequest, request: Request
    ) -> dict[str, Any]:
        ctx = await context_factory(request)
        _ensure_identity(ctx)
        ctx.session_id = session_id
        runner = await runner_factory(ctx)
        result = await runner.resume(session_id, body.results)
        return result.model_dump()

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str, request: Request) -> dict[str, Any]:
        ctx = await context_factory(request)
        _ensure_identity(ctx)
        runner = await runner_factory(ctx)
        session = await runner.session_manager.load_session(
            session_id,
            scope=runner._session_scope(),
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.model_dump(mode="json")

    return router
