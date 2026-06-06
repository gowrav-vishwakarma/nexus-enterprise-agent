"""Talk-in-the-browser demo for the cascaded voice pipeline (real local models).

Push-to-talk web UI: record your mic, the audio goes STT -> LLM -> TTS using the
self-hosted ``local-ai-stack`` servers, and the spoken reply plays back. Nothing
is mocked and no paid API is used.

Prereqs (in the separate local-ai-stack folder):
    ./run-stt.sh      # faster-whisper  :8001
    ./run-tts.sh      # Kokoro          :8002
    # Ollama already serving gpt-oss    :11434

Run:
    uv run --extra fastapi uvicorn examples.realtime_local_voice_ui:app --port 8080
Then open http://localhost:8080/ and allow microphone access.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.runtime import RealtimeRuntime
from nexus.tools.context import RunContext

MANIFEST = Path(
    os.environ.get(
        "NEXUS_VOICE_MANIFEST",
        str(Path(__file__).parent / "orchestration" / "voice_local.yaml"),
    )
)

app = FastAPI(title="NEXUS Local Voice (cascaded)")
_runtime: RealtimeRuntime | None = None
_pipeline = None


def _get_pipeline():
    """Build the cascaded pipeline once and reuse it (keeps session memory)."""
    global _runtime, _pipeline
    if _pipeline is None:
        manifest = OrchestrationManifest.load(str(MANIFEST))
        _runtime = RealtimeRuntime.from_manifest(
            manifest, run_context=RunContext(session_id="browser-voice")
        )
        _pipeline = _runtime.build_pipeline()
    return _pipeline


@app.post("/api/talk")
async def talk(request: Request) -> JSONResponse:
    """Accept a recorded audio blob, run STT->LLM->TTS, return text + spoken reply."""
    audio = await request.body()
    mime = request.headers.get("content-type", "audio/webm")
    session_id = request.headers.get("x-session-id", "browser-voice")

    transcript, reply = "", ""
    audio_chunks: list[bytes] = []
    async for ev in _get_pipeline().process_utterance(
        audio, session_id=session_id, mime_type=mime
    ):
        if ev.event_type == "transcript_final" and ev.content:
            transcript = ev.content
        elif ev.event_type == "final_response" and ev.content:
            reply = ev.content
        elif ev.event_type == "content" and ev.content and not reply:
            reply += ev.content
        elif ev.event_type == "audio_out" and ev.audio:
            audio_chunks.append(ev.audio)

    wav = b"".join(audio_chunks)
    return JSONResponse(
        {
            "transcript": transcript,
            "reply": reply,
            "audio_b64": base64.b64encode(wav).decode("ascii") if wav else None,
        }
    )


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>NEXUS Local Voice</title>
<style>
 body{font-family:system-ui;margin:2rem auto;max-width:640px;color:#111}
 h1{font-size:1.3rem} .sub{color:#666;margin-top:-.4rem}
 #talk{padding:1rem 1.6rem;font-size:1.1rem;border:0;border-radius:999px;
   background:#2563eb;color:#fff;cursor:pointer}
 #talk.rec{background:#dc2626}
 #log{margin-top:1.5rem;display:flex;flex-direction:column;gap:.6rem}
 .msg{padding:.6rem .9rem;border-radius:.8rem;max-width:85%}
 .you{background:#e5e7eb;align-self:flex-end}
 .bot{background:#dbeafe;align-self:flex-start}
 .status{color:#888;font-size:.85rem}
</style></head>
<body>
<h1>NEXUS Local Voice</h1>
<p class="sub">Cascaded STT &rarr; LLM &rarr; TTS, 100% local (faster-whisper + Ollama + Kokoro).</p>
<button id="talk">Hold to talk</button>
<span class="status" id="status"></span>
<div id="log"></div>
<script>
const sid = 'sess-' + Math.random().toString(36).slice(2);
const btn = document.getElementById('talk');
const logEl = document.getElementById('log');
const statusEl = document.getElementById('status');
let rec, chunks = [], mediaStream;

function add(cls, text){ const d=document.createElement('div'); d.className='msg '+cls; d.textContent=text; logEl.appendChild(d); window.scrollTo(0,document.body.scrollHeight); }

async function startRec(){
  mediaStream = await navigator.mediaDevices.getUserMedia({audio:true});
  rec = new MediaRecorder(mediaStream, {mimeType:'audio/webm'});
  chunks = [];
  rec.ondataavailable = e => { if(e.data.size) chunks.push(e.data); };
  rec.onstop = sendAudio;
  rec.start();
  btn.classList.add('rec'); btn.textContent='Release to send'; statusEl.textContent='listening...';
}
function stopRec(){
  if(rec && rec.state!=='inactive') rec.stop();
  if(mediaStream) mediaStream.getTracks().forEach(t=>t.stop());
  btn.classList.remove('rec'); btn.textContent='Hold to talk';
}
async function sendAudio(){
  const blob = new Blob(chunks, {type:'audio/webm'});
  statusEl.textContent='thinking...';
  const res = await fetch('/api/talk', {method:'POST', headers:{'Content-Type':'audio/webm','x-session-id':sid}, body: blob});
  const data = await res.json();
  if(data.transcript) add('you', data.transcript);
  if(data.reply) add('bot', data.reply);
  statusEl.textContent='';
  if(data.audio_b64){ const a=new Audio('data:audio/wav;base64,'+data.audio_b64); a.play(); }
}
btn.addEventListener('mousedown', startRec);
btn.addEventListener('mouseup', stopRec);
btn.addEventListener('touchstart', e=>{e.preventDefault();startRec();});
btn.addEventListener('touchend', e=>{e.preventDefault();stopRec();});
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Serve the push-to-talk demo page."""
    _get_pipeline()  # warm the pipeline on first load
    return _PAGE
