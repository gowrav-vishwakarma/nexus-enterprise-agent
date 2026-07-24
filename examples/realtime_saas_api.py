"""NEXUS realtime SaaS example: voice over WebSocket + session bootstrap.

This is the realtime counterpart to ``nexus_saas_api.py``. It exposes:

  POST /v1/realtime/sessions     Create a realtime session; returns the WS URL
                                 and the audio format the client should send.
  WS   /v1/realtime/ws/{sid}     Bidirectional voice: client sends PCM16 frames
                                 (binary), receives JSON events + audio.
  POST /v1/channels/{name}/webhook   Messaging channels (Telegram/WhatsApp).
  POST /v1/realtime/sip/inbound      SIP/telephony inbound webhook (returns a WS url).

Voice agents are defined in YAML manifests (see examples/orchestration/*.yaml).
STT/TTS default to "mock" so this runs without provider keys; set real providers
and keys in the manifest/env for production audio.

Run:
    uv run --extra fastapi --extra realtime --extra openai \
        uvicorn examples.realtime_saas_api:app --reload
"""

from __future__ import annotations

import os
import pathlib
from typing import Optional
from uuid import uuid4

try:
    from dotenv import load_dotenv

    _env = pathlib.Path(__file__).parent.parent / ".env"
    if _env.exists():
        load_dotenv(dotenv_path=_env)
except ImportError:
    pass

from fastapi import FastAPI, Header, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel

from nexus.channels import (
    ChannelRegistry,
    ChannelRouter,
    StaticIdentityResolver,
    TelegramAdapter,
    WhatsAppAdapter,
)
from nexus.config.agent import AgentConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.adapters.factory import build_stt
from nexus.realtime.config import STTConfig
from nexus.realtime.multimodal.runner import VisionAgentRunner
from nexus.realtime.runtime import RealtimeRuntime
from nexus.realtime.session import RealtimeSession
from nexus.realtime.transport.websocket import WebSocketTransport
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

ORCH_DIR = pathlib.Path(__file__).parent / "orchestration"
MANIFESTS = {
    "voice_grpc": ORCH_DIR / "voice_grpc.yaml",
    "ivr_support": ORCH_DIR / "ivr_support.yaml",
}

# ── Plan-tier gating ─────────────────────────────────────────────────────────
# Voice is expensive; gate which agents/modalities/concurrency each plan allows.
REALTIME_PLANS: dict[str, dict] = {
    "free": {"agents": [], "modalities": [], "max_concurrent": 0},
    "starter": {
        "agents": ["ivr_support"],
        "modalities": ["voice_cascaded"],
        "max_concurrent": 2,
    },
    "pro": {
        "agents": ["ivr_support", "voice_grpc"],
        "modalities": ["voice_cascaded"],
        "max_concurrent": 10,
    },
    "enterprise": {
        "agents": ["ivr_support", "voice_grpc"],
        "modalities": ["voice_cascaded", "voice_s2s"],
        "max_concurrent": 100,
    },
}


class RealtimeAccessError(Exception):
    """Raised when a tenant's plan does not allow a realtime request."""


def check_realtime_access(plan: str, agent: str, modality: str = "voice_cascaded") -> dict:
    """Return the plan's realtime features or raise RealtimeAccessError.

    Pure function so it is easy to unit test independently of FastAPI.
    """
    features = REALTIME_PLANS.get(plan)
    if features is None:
        raise RealtimeAccessError(f"Unknown plan: {plan!r}")
    if agent not in features["agents"]:
        raise RealtimeAccessError(f"Plan {plan!r} cannot use agent {agent!r}")
    if modality not in features["modalities"]:
        raise RealtimeAccessError(f"Plan {plan!r} cannot use modality {modality!r}")
    return features


# Naive in-memory concurrency counter (per tenant). Use Redis in production.
_ACTIVE_SESSIONS: dict[str, int] = {}

app = FastAPI(title="NEXUS Realtime SaaS Example")


def _load_manifest(agent: str) -> OrchestrationManifest:
    path = MANIFESTS.get(agent)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown realtime agent: {agent}")
    return OrchestrationManifest.load(path)


class RealtimeSessionRequest(BaseModel):
    agent: str = "voice_grpc"
    modality: str = "voice_cascaded"
    session_id: Optional[str] = None


@app.post("/v1/realtime/sessions")
async def create_realtime_session(
    body: RealtimeSessionRequest,
    request: Request,
    x_tenant_id: str = Header(default="demo", alias="X-Tenant-ID"),
    x_user_id: str = Header(default="demo-user", alias="X-User-ID"),
    x_plan: str = Header(default="pro", alias="X-Plan"),
):
    """Bootstrap a realtime session and return how to connect.

    In production this is where you would mint a short-lived token (e.g. an
    ephemeral WebSocket secret or signed session URL). Here we return the
    WebSocket URL and the audio format the browser should stream.
    """
    if body.agent not in MANIFESTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {body.agent}")

    try:
        check_realtime_access(x_plan, body.agent, body.modality)
    except RealtimeAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    session_id = body.session_id or str(uuid4())
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", "localhost:8000")
    ws_url = f"{scheme}://{host}/v1/realtime/ws/{session_id}?agent={body.agent}"

    return {
        "session_id": session_id,
        "agent": body.agent,
        "ws_url": ws_url,
        "audio": {"encoding": "pcm16", "sample_rate": 16000, "channels": 1},
        "tenant_id": x_tenant_id,
        "user_id": x_user_id,
        "plan": x_plan,
    }


@app.websocket("/v1/realtime/ws/{session_id}")
async def realtime_ws(websocket: WebSocket, session_id: str):
    """Bidirectional voice over WebSocket.

    Client sends binary PCM16 frames (and optional JSON control messages);
    server streams JSON events and (binary) synthesized audio back.
    """
    await websocket.accept()
    params = websocket.query_params
    agent = params.get("agent", "voice_grpc")
    tenant_id = params.get("tenant_id", "demo")
    user_id = params.get("user_id", "demo-user")
    plan = params.get("plan", "pro")

    try:
        manifest = _load_manifest(agent)
    except HTTPException:
        await websocket.close(code=4404)
        return

    # Enforce plan gating + concurrency at connect time.
    try:
        features = check_realtime_access(plan, agent)
    except RealtimeAccessError as exc:
        await websocket.close(code=4403, reason=str(exc)[:120])
        return

    active = _ACTIVE_SESSIONS.get(tenant_id, 0)
    if active >= features["max_concurrent"]:
        await websocket.close(code=4429, reason="Concurrent session limit reached")
        return
    _ACTIVE_SESSIONS[tenant_id] = active + 1

    run_context = RunContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    runtime = RealtimeRuntime.from_manifest(manifest, run_context=run_context)
    pipeline = runtime.build_pipeline(agent)

    # Let JSON control frames update DTMF / inject text turns.
    def on_control(payload: dict) -> None:
        if "dtmf" in payload:
            buffer = str(run_context.metadata.get("dtmf_buffer", ""))
            run_context.metadata["dtmf_buffer"] = buffer + str(payload["dtmf"])

    transport = WebSocketTransport(websocket, on_control=on_control)
    session = RealtimeSession(pipeline, transport, session_id=session_id)

    from starlette.websockets import WebSocketDisconnect

    try:
        await session.run_audio()
    except WebSocketDisconnect:
        return
    except Exception as exc:  # pragma: no cover - connection errors
        await websocket.close(code=1011, reason=str(exc)[:120])
    finally:
        _ACTIVE_SESSIONS[tenant_id] = max(0, _ACTIVE_SESSIONS.get(tenant_id, 1) - 1)


@app.websocket("/v1/realtime/twilio/{session_id}")
async def twilio_media_ws(websocket: WebSocket, session_id: str):
    """Twilio Media Streams bridge: mu-law 8 kHz audio over WebSocket.

    Point a Twilio ``<Stream>`` at this URL. Inbound mu-law is decoded to PCM16
    for the IVR pipeline; synthesized audio is encoded back to mu-law. DTMF key
    presses are fed to the ``ivr_menu`` tools via ``dtmf_buffer``.
    """
    await websocket.accept()
    agent = websocket.query_params.get("agent", "ivr_support")
    tenant_id = websocket.query_params.get("tenant_id", "demo")

    try:
        manifest = _load_manifest(agent)
    except HTTPException:
        await websocket.close(code=4404)
        return

    run_context = RunContext(tenant_id=tenant_id, user_id=f"caller:{session_id}", session_id=session_id)
    runtime = RealtimeRuntime.from_manifest(manifest, run_context=run_context)
    pipeline = runtime.build_pipeline(agent)

    def on_dtmf(digit: str) -> None:
        buffer = str(run_context.metadata.get("dtmf_buffer", ""))
        run_context.metadata["dtmf_buffer"] = buffer + digit

    from nexus.realtime.transport.sip import TwilioMediaStreamTransport

    tts_rate = pipeline.config.effective_tts().sample_rate if hasattr(pipeline, "config") else 8000
    transport = TwilioMediaStreamTransport(websocket, on_dtmf=on_dtmf, tts_sample_rate=tts_rate)
    session = RealtimeSession(pipeline, transport, session_id=session_id)

    from starlette.websockets import WebSocketDisconnect

    try:
        await session.run_audio()
    except WebSocketDisconnect:
        return


@app.post("/v1/realtime/sip/inbound")
async def sip_inbound(request: Request):
    """SIP/telephony inbound webhook.

    Telephony providers (Twilio, Telnyx) post call metadata here; we answer by
    returning the media WebSocket URL the provider should stream the call audio
    to. See ``nexus.realtime.transport.sip`` for the bridge helper.
    """
    payload = await request.json()
    call_id = payload.get("call_id") or payload.get("CallSid") or str(uuid4())
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", "localhost:8000")
    return {
        "session_id": call_id,
        "stream_url": f"{scheme}://{host}/v1/realtime/twilio/{call_id}?agent=ivr_support",
        "audio": {"encoding": "mulaw", "sample_rate": 8000, "channels": 1},
    }


# ── Messaging channels (Telegram, WhatsApp, ...) ─────────────────────────────
# One generic webhook routes any registered channel through the SAME agent core.
# Attachments reuse STT (voice notes) and vision (images): see ChannelRouter.

# The messaging-channel demo is intentionally tool-less. To give the assistant
# capabilities, build a ToolRegistry with add_tool()/add_toolset() and point
# _text_agent_config() at a toolset via AgentConfig.toolset.
SHARED_TOOL_REGISTRY = ToolRegistry()
SHARED_SESSION_MANAGER = SessionManager()
CHANNELS = ChannelRegistry()


def _register_channels() -> None:
    """Register messaging adapters from environment configuration."""
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if tg_token:
        CHANNELS.register(TelegramAdapter(tg_token, name="telegram"))
    wa_token = os.getenv("WHATSAPP_TOKEN")
    wa_phone = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if wa_token and wa_phone:
        CHANNELS.register(WhatsAppAdapter(wa_token, wa_phone, name="whatsapp"))


_register_channels()


def _text_agent_config() -> AgentConfig:
    return AgentConfig(
        name="channel_assistant",
        llm=LLMProviderConfig(
            provider="openai",
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY", "mock-key"),
        ),
        persona=AgentPersonaConfig(
            role="Messaging Assistant", goal="Help users over chat channels"
        ),
    )


def _make_router(channel_name: str) -> ChannelRouter:
    """Build a ChannelRouter wiring a channel to the agent core."""
    adapter = CHANNELS.get(channel_name)

    def executor_factory(ctx: RunContext) -> AgentRunner:
        return AgentRunner(
            config=_text_agent_config(),
            tool_registry=SHARED_TOOL_REGISTRY,
            storage_config=SHARED_SESSION_MANAGER,
            run_context=ctx,
        )

    def vision_executor_factory(ctx: RunContext) -> VisionAgentRunner:
        cfg = _text_agent_config()
        cfg.llm.model = os.getenv("OPENAI_VISION_MODEL", "gpt-4o")
        return VisionAgentRunner(
            config=cfg,
            tool_registry=SHARED_TOOL_REGISTRY,
            storage_config=SHARED_SESSION_MANAGER,
            run_context=ctx,
        )

    stt = build_stt(STTConfig(provider=os.getenv("NEXUS_STT_PROVIDER", "mock")))
    return ChannelRouter(
        adapter,
        executor_factory,
        identity_resolver=StaticIdentityResolver(tenant_id=os.getenv("NEXUS_TENANT_ID", "demo")),
        stt=stt,
        vision_executor_factory=vision_executor_factory,
    )


@app.get("/v1/channels/whatsapp/webhook")
async def whatsapp_verify(request: Request):
    """WhatsApp webhook verification handshake (echo hub.challenge)."""
    params = request.query_params
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "nexus-verify")
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == verify_token:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/v1/channels/{name}/webhook")
async def channel_webhook(name: str, request: Request):
    """Generic inbound webhook for any registered messaging channel."""
    if not CHANNELS.has(name):
        raise HTTPException(status_code=404, detail=f"Channel {name!r} not configured")
    payload = await request.json()
    router = _make_router(name)
    output = await router.handle(payload)
    # Providers expect a fast 200; the reply was already sent via the adapter.
    return {"status": "ok", "session_id": output.session_id}
