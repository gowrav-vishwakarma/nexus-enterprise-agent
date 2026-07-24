"""Nexus Voice Lab — full-duplex browser UI for real end-to-end voice testing.

Uses env-driven manifest + gRPC media servers + liteLLM for LLM. Not a mock demo:
configure STT/TTS/VAD engines and LLM in ``.env``, start media servers, then talk.

Quick start:
    cp .env.example .env   # edit LITELLM_*, STT_ENGINE, TTS_ENGINE, devices
    ./scripts/run_voice_lab.sh

Or manually:
    uv run python -m nexus.server up -c examples/servers.yaml
    uv run --extra fastapi --extra realtime --extra litellm --extra grpc \\
        uvicorn examples.voice_lab:app --host 0.0.0.0 --port 8787

Open http://localhost:8787 — allow microphone, click the mic button.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

try:
    from dotenv import load_dotenv

    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        load_dotenv(dotenv_path=_env, override=True)
except ImportError:
    pass

# voice_grpc.yaml uses LITELLM_* / VOICE_LLM_* — accept ankpal-voice + NEXUS_LLM_* aliases
for _src, _dst in (
    ("LLM_BASE_URL", "LITELLM_BASE_URL"),
    ("LLM_SECRET", "LITELLM_API_KEY"),
    ("LLM_MODEL", "VOICE_LLM_MODEL"),
    ("NEXUS_LLM_BASE_URL", "LITELLM_BASE_URL"),
    ("NEXUS_LLM_API_KEY", "LITELLM_API_KEY"),
    ("NEXUS_LLM_MODEL", "VOICE_LLM_MODEL"),
    ("STT_LANGUAGE", "VOICE_DEFAULT_LANGUAGE"),
    ("MIN_SILENCE_MS", "VAD_SILENCE_MS"),
):
    if os.getenv(_src) and not os.getenv(_dst):
        os.environ[_dst] = os.environ[_src]

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse

from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.config import RealtimeAgentConfig
from nexus.realtime.runtime import RealtimeRuntime, resolve_realtime_agent
from nexus.realtime.session import RealtimeSession
from nexus.realtime.transport.websocket import WebSocketTransport
from nexus.server.config import ModelServerSpec, ServersConfig
from nexus.server.registry import ServerRegistry
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

from examples.orchestration.voice_grpc_tools import register_voice_tools

if TYPE_CHECKING:
    from nexus.realtime.events import RealtimeStreamEvent


class _LoggingTransport(WebSocketTransport):
    """Log every outbound realtime event to the server console."""

    def __init__(self, ws: Any, *, session_id: str, **kwargs: Any) -> None:
        super().__init__(ws, **kwargs)
        self._session_id = session_id

    async def send_event(self, event: "RealtimeStreamEvent") -> None:
        payload = event.content or event.data
        if event.event_type == "error":
            logger.error("[%s] %s", self._session_id, payload)
        else:
            logger.info("[%s] %s %s", self._session_id, event.event_type, payload)
        await super().send_event(event)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = Path(
    os.environ.get("NEXUS_VOICE_MANIFEST", str(ROOT / "orchestration" / "voice_grpc.yaml"))
)
SERVERS_PATH = Path(os.environ.get("NEXUS_SERVERS_CONFIG", str(ROOT / "servers.yaml")))
AGENT_NAME = os.environ.get("NEXUS_VOICE_AGENT", "voice_grpc")
LAB_PORT = int(os.environ.get("VOICE_LAB_PORT", "8787"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Pipeline + LLM + media adapter logs to console during voice sessions.
    for name in ("nexus.runner", "nexus.llm", "nexus.realtime", "nexus.server", "examples.voice_lab"):
        logging.getLogger(name).setLevel(logging.INFO)
    _load_manifest()
    refs = _media_server_refs()
    if _registry and refs:
        results = await _registry.check_all(refs)
        bad = [k for k, v in results.items() if not v]
        if bad:
            logger.warning(
                "Media server(s) not healthy: %s — start with: "
                "uv run python -m nexus.server up -c %s",
                ", ".join(bad),
                SERVERS_PATH,
            )
        else:
            logger.info("All media servers healthy: %s", ", ".join(refs))

    global _language_validation
    cfg = _rt_config or resolve_realtime_agent(AGENT_NAME, _load_manifest(), RunContext())
    from nexus.realtime.validation import run_startup_language_validation

    issues = await run_startup_language_validation(
        cfg,
        servers=_manifest_servers(),
        server_registry=_registry,
    )
    _language_validation = [
        {"severity": i.severity, "code": i.code, "message": i.message} for i in issues
    ]
    yield


app = FastAPI(title="Nexus Voice Lab", description="Real voice testing UI for the framework", lifespan=lifespan)

_manifest: OrchestrationManifest | None = None
_registry: ServerRegistry | None = None
_rt_config: RealtimeAgentConfig | None = None
_language_validation: list[dict[str, str]] = []

# Pre-built tool registry for the voice agent. The manifest selects the
# voice_tools pack via `agent.toolset: voice_tools`.
_TOOL_REGISTRY: ToolRegistry = register_voice_tools(ToolRegistry())


def _load_manifest() -> OrchestrationManifest:
    global _manifest, _registry, _rt_config
    if _manifest is None:
        _manifest = OrchestrationManifest.load(str(MANIFEST_PATH))
        servers = _manifest.schema.servers
        if servers:
            specs = {n: ModelServerSpec(**s) if isinstance(s, dict) else s for n, s in servers.items()}
            _registry = ServerRegistry(ServersConfig(servers=specs))
        _rt_config = resolve_realtime_agent(
            AGENT_NAME,
            _manifest,
            RunContext(tenant_id="lab", user_id="bootstrap"),
        )
    return _manifest


def _media_server_refs() -> list[str]:
    cfg = _rt_config or resolve_realtime_agent(
        AGENT_NAME, _load_manifest(), RunContext()
    )
    refs: list[str] = []
    for block in (cfg.stt, cfg.tts, cfg.vad, cfg.lid):
        if block and getattr(block, "server_ref", None):
            if block.provider.lower() in ("nexus_server", "grpc", "nexus"):
                refs.append(block.server_ref)
    return refs



def _manifest_servers() -> dict[str, ModelServerSpec]:
    manifest = _load_manifest()
    raw = manifest.schema.servers or {}
    return {n: ModelServerSpec(**s) if isinstance(s, dict) else s for n, s in raw.items()}


def _safe_llm_dict() -> dict[str, Any]:
    cfg = _rt_config
    if cfg is None:
        return {}
    llm = cfg.agent.llm
    return {
        "provider": llm.provider,
        "model": llm.model,
        "base_url": llm.base_url,
        "max_tokens": (llm.default_params or {}).get("max_tokens"),
    }




@app.get("/")
async def index() -> FileResponse:
    """Serve the voice lab browser UI."""
    return FileResponse(ROOT / "static" / "voice_lab.html")


@app.get("/api/status")
async def api_status() -> JSONResponse:
    """Return current env-driven config and media server health."""
    manifest = _load_manifest()
    cfg = _rt_config or resolve_realtime_agent(AGENT_NAME, manifest, RunContext())
    servers_info: list[dict[str, Any]] = []
    media_ready = True
    if _registry:
        refs = _media_server_refs()
        # Health-check every configured server for the status panel (not only STT/TTS refs).
        await _registry.check_all()
        for row in _registry.list_servers():
            servers_info.append(row)
            if refs and row["name"] in refs and not row["healthy"]:
                media_ready = False
    stt = cfg.effective_stt()
    tts = cfg.effective_tts()
    vad = cfg.effective_vad()
    lid = cfg.effective_lid()
    lid_info = None
    if lid:
        lid_info = {
            "provider": lid.provider,
            "server_ref": lid.server_ref,
            "fallback_language": lid.fallback_language,
        }
    return JSONResponse(
        {
            "manifest": str(MANIFEST_PATH),
            "servers_config": str(SERVERS_PATH),
            "agent": AGENT_NAME,
            "tenant_id": os.environ.get("NEXUS_TENANT_ID", "lab"),
            "user_id": os.environ.get("NEXUS_USER_ID", "tester"),
            "llm": _safe_llm_dict(),
            "stt": {
                "provider": stt.provider,
                "server_ref": stt.server_ref,
                "base_url": stt.base_url,
                "language": stt.language,
            },
            "tts": {
                "provider": tts.provider,
                "server_ref": tts.server_ref,
                "sample_rate": tts.sample_rate,
                "voice": (tts.voice or "")[:60],
            },
            "vad": {"provider": vad.provider, "server_ref": vad.server_ref},
            "lid": lid_info,
            "per_turn_language": lid is not None,
            "audio": {"encoding": "pcm16", "sample_rate": 16000, "play_sample_rate": tts.sample_rate},
            "playback": {"sample_rate": tts.sample_rate},
            "servers": servers_info,
            "media_ready": media_ready,
            "language_validation": _language_validation,
        }
    )


@app.get("/api/health")
async def api_health() -> JSONResponse:
    """Preflight: all referenced media servers must be healthy."""
    _load_manifest()
    refs = _media_server_refs()
    if not _registry or not refs:
        return JSONResponse({"status": "ok", "message": "no gRPC media servers configured"})
    results = await _registry.check_all(refs)
    bad = [k for k, v in results.items() if not v]
    if bad:
        raise HTTPException(
            status_code=503,
            detail=f"Media servers not healthy: {', '.join(bad)}. "
            f"Run: uv run python -m nexus.server up -c {SERVERS_PATH}",
        )
    return JSONResponse({"status": "ok", "servers": results})


@app.post("/v1/realtime/sessions")
async def create_session(
    request: Request,
    x_tenant_id: str = Header(default="lab", alias="X-Tenant-ID"),
    x_user_id: str = Header(default="tester", alias="X-User-ID"),
) -> JSONResponse:
    """Bootstrap a voice WebSocket session."""
    manifest = _load_manifest()
    cfg = _rt_config or resolve_realtime_agent(AGENT_NAME, manifest, RunContext())
    refs = _media_server_refs()
    if _registry and refs:
        try:
            await _registry.require_healthy(refs)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    session_id = str(uuid4())
    tts_rate = cfg.effective_tts().sample_rate
    return JSONResponse(
        {
            "session_id": session_id,
            "agent": AGENT_NAME,
            "ws_path": f"/v1/realtime/ws/{session_id}",
            "audio": {"encoding": "pcm16", "sample_rate": 16000, "channels": 1},
            "playback": {"sample_rate": tts_rate},
            "tenant_id": x_tenant_id,
            "user_id": x_user_id,
        }
    )


@app.websocket("/v1/realtime/ws/{session_id}")
async def voice_ws(
    websocket: WebSocket,
    session_id: str,
    tenant_id: str = "lab",
    user_id: str = "tester",
):
    """Full-duplex voice: PCM16 uplink, JSON events + PCM16 downlink."""
    await websocket.accept()
    params = websocket.query_params
    tenant_id = params.get("tenant_id", tenant_id)
    user_id = params.get("user_id", user_id)

    manifest = _load_manifest()
    run_context = RunContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id)
    runtime = RealtimeRuntime.from_manifest(
        manifest, run_context=run_context, tool_registry=_TOOL_REGISTRY
    )
    pipeline = runtime.build_pipeline(AGENT_NAME)
    transport = _LoggingTransport(websocket, session_id=session_id)
    session = RealtimeSession(pipeline, transport, session_id=session_id)

    from starlette.websockets import WebSocketDisconnect

    try:
        await session.run_audio()
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.exception("Voice session error")
        try:
            await websocket.close(code=1011, reason=str(exc)[:120])
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "examples.voice_lab:app",
        host=os.environ.get("VOICE_LAB_HOST", "0.0.0.0"),
        port=LAB_PORT,
        reload=bool(os.environ.get("VOICE_LAB_RELOAD")),
    )
