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
from nexus.realtime.audio import merge_wav_chunks
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

    transcript, reply, info, error = "", "", None, None
    audio_chunks: list[bytes] = []
    try:
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
            elif ev.event_type == "event" and ev.data:
                info = ev.data.get("info") or info
            elif ev.event_type == "error":
                error = ev.content or str(ev.data)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    wav = merge_wav_chunks(audio_chunks)
    if not error and not transcript and info == "empty_transcript":
        error = (
            "No Hindi speech detected — speak in Hindi (not English). "
            "Check the mic level while holding the button."
        )
    elif not error and transcript and reply and not wav:
        error = "Reply was generated but TTS returned no audio."

    return JSONResponse(
        {
            "transcript": transcript,
            "reply": reply,
            "audio_b64": base64.b64encode(wav).decode("ascii") if wav else None,
            "info": info,
            "error": error,
            "audio_bytes": len(audio),
            "mic_peak": request.headers.get("x-mic-peak"),
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
<p class="sub">Cascaded STT &rarr; LLM &rarr; TTS, 100% local. <strong>Speak Hindi</strong> — mic level shows while you hold the button.</p>
<button id="talk">Hold to talk</button>
<span class="status" id="status"></span>
<div id="log"></div>
<script>
const sid = 'sess-' + Math.random().toString(36).slice(2);
const btn = document.getElementById('talk');
const logEl = document.getElementById('log');
const statusEl = document.getElementById('status');
let rec, chunks = [], mediaStream, recStart = 0, audioCtx, analyser, levelTimer, peakLevel = 0;
const MIN_RECORD_MS = 700;
const MIN_PEAK_LEVEL = 8;
const webmMime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
  ? 'audio/webm;codecs=opus' : 'audio/webm';

function stopLevelMeter(){
  if(levelTimer){ clearInterval(levelTimer); levelTimer = null; }
  if(audioCtx){ audioCtx.close().catch(()=>{}); audioCtx = null; }
}

function add(cls, text){ const d=document.createElement('div'); d.className='msg '+cls; d.textContent=text; logEl.appendChild(d); window.scrollTo(0,document.body.scrollHeight); }

async function startRec(){
  if(rec && rec.state!=='inactive') return;
  stopLevelMeter();
  peakLevel = 0;
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true}
  });
  audioCtx = new AudioContext();
  const source = audioCtx.createMediaStreamSource(mediaStream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  source.connect(analyser);
  const levelData = new Uint8Array(analyser.frequencyBinCount);
  levelTimer = setInterval(() => {
    analyser.getByteFrequencyData(levelData);
    let max = 0;
    for (const v of levelData) if (v > max) max = v;
    peakLevel = Math.max(peakLevel, max);
    statusEl.textContent = 'listening... mic ' + max + (max < MIN_PEAK_LEVEL ? ' (speak louder)' : '');
  }, 120);

  rec = new MediaRecorder(mediaStream, {mimeType: webmMime});
  chunks = [];
  rec.ondataavailable = e => { if(e.data && e.data.size) chunks.push(e.data); };
  recStart = Date.now();
  rec.start(100);
  btn.classList.add('rec'); btn.textContent='Release to send';
}
async function stopRec(){
  if(!rec || rec.state==='inactive') return;
  btn.classList.remove('rec'); btn.textContent='Hold to talk';
  await new Promise(resolve => {
    rec.addEventListener('stop', resolve, {once:true});
    rec.stop();
  });
  stopLevelMeter();
  await sendAudio();
  if(mediaStream) mediaStream.getTracks().forEach(t=>t.stop());
}
async function sendAudio(){
  const heldMs = Date.now() - recStart;
  if(heldMs < MIN_RECORD_MS){
    statusEl.textContent='Hold the button a little longer while speaking.';
    chunks = [];
    return;
  }
  if(!chunks.length){ statusEl.textContent='No audio captured — try again.'; return; }
  const blob = new Blob(chunks, {type: webmMime});
  if(blob.size < 512){
    statusEl.textContent='Recording too small — hold longer and speak clearly.';
    chunks = [];
    return;
  }
  if(peakLevel < MIN_PEAK_LEVEL){
    statusEl.textContent='Mic level too low ('+peakLevel+') — pick the right input device in browser/OS settings.';
    chunks = [];
    return;
  }
  statusEl.textContent='thinking... ('+Math.round(blob.size/1024)+' KB, peak '+peakLevel+')';
  try {
    const res = await fetch('/api/talk', {method:'POST', headers:{
      'Content-Type':'audio/webm','x-session-id':sid,'x-mic-peak':String(peakLevel)
    }, body: blob});
    const data = await res.json();
    if(!res.ok) throw new Error(data.error || data.detail || ('HTTP '+res.status));
    if(data.transcript) add('you', data.transcript);
    if(data.reply) add('bot', data.reply);
    if(data.error){
      let msg = data.error;
      if(data.mic_peak) msg += ' [mic peak '+data.mic_peak+', '+data.audio_bytes+' bytes]';
      statusEl.textContent = msg;
    }
    else if(data.audio_b64){
      const a = new Audio('data:audio/wav;base64,'+data.audio_b64);
      a.onended = () => { statusEl.textContent = ''; };
      try { await a.play(); statusEl.textContent = 'speaking...'; }
      catch(e){ statusEl.textContent = 'Audio blocked: ' + e; }
    } else if(!data.error) {
      statusEl.textContent = 'No spoken reply — check mic/STT.';
    }
  } catch(e) {
    statusEl.textContent = 'Error: ' + e;
  }
}
btn.addEventListener('mousedown', () => { startRec().catch(e => { statusEl.textContent = 'Mic error: ' + e; }); });
btn.addEventListener('mouseup', () => { stopRec().catch(e => { statusEl.textContent = 'Stop error: ' + e; }); });
btn.addEventListener('touchstart', e=>{e.preventDefault(); startRec().catch(err => { statusEl.textContent = 'Mic error: ' + err; });});
btn.addEventListener('touchend', e=>{e.preventDefault(); stopRec().catch(err => { statusEl.textContent = 'Stop error: ' + err; });});
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Serve the push-to-talk demo page."""
    _get_pipeline()  # warm the pipeline on first load
    return _PAGE
