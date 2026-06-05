"""Full-duplex talk-in-the-browser demo for real speech-to-speech (Kyutai Moshi).

The browser streams mic PCM16 (24 kHz) over a WebSocket; the framework's S2S
pipeline drives a self-hosted Moshi server and streams spoken audio + text back
live (you can talk over it / barge in). Nothing is mocked, no paid API.

Prereqs:
    # in local-ai-stack (separate folder):
    ./run-s2s-moshi.sh          # real Moshi model server :8998 (first run downloads weights)
    # in agent-framework:
    uv sync --extra moshi --extra fastapi   # client deps (websockets, sphn, numpy)

Run:
    uv run --extra fastapi --extra moshi uvicorn examples.realtime_s2s_ui:app --port 8081
Then open http://localhost:8081/ and allow microphone access.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.runtime import RealtimeRuntime
from nexus.tools.context import RunContext

MANIFEST = Path(__file__).parent / "orchestration" / "voice_s2s_local.yaml"

app = FastAPI(title="NEXUS Local Voice (speech-to-speech)")
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        manifest = OrchestrationManifest.load(str(MANIFEST))
        runtime = RealtimeRuntime.from_manifest(
            manifest, run_context=RunContext(session_id="browser-s2s")
        )
        _pipeline = runtime.build_pipeline()
    return _pipeline


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """Bridge the browser's PCM stream to the S2S pipeline, both directions."""
    await ws.accept()
    audio_q: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def receiver() -> None:
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await audio_q.put(msg["bytes"])
                elif msg.get("text") == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            await audio_q.put(None)

    async def audio_in():
        while True:
            chunk = await audio_q.get()
            if chunk is None:
                break
            yield chunk

    recv_task = asyncio.create_task(receiver())
    try:
        async for ev in _get_pipeline().process_audio_stream(audio_in(), session_id="browser-s2s"):
            if ev.event_type == "audio_out" and ev.audio:
                await ws.send_bytes(ev.audio)
            elif ev.event_type in ("content", "transcript_final") and ev.content:
                await ws.send_json({"type": "text", "text": ev.content})
            elif ev.event_type == "error":
                await ws.send_json({"type": "error", "text": str(ev.data or ev.content)})
    except WebSocketDisconnect:
        pass
    finally:
        recv_task.cancel()


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>NEXUS S2S</title>
<style>
 body{font-family:system-ui;margin:2rem auto;max-width:640px;color:#111}
 h1{font-size:1.3rem}.sub{color:#666;margin-top:-.4rem}
 button{padding:1rem 1.6rem;font-size:1.1rem;border:0;border-radius:999px;background:#7c3aed;color:#fff;cursor:pointer}
 button.on{background:#dc2626}
 #txt{margin-top:1.5rem;white-space:pre-wrap;border:1px solid #ddd;border-radius:.6rem;padding:1rem;min-height:120px}
 .status{color:#888;font-size:.85rem;margin-left:.6rem}
</style></head>
<body>
<h1>NEXUS Speech-to-Speech</h1>
<p class="sub">Full-duplex, real model (Kyutai Moshi), 100% local. Just talk &mdash; it talks back.</p>
<button id="btn">Start conversation</button><span class="status" id="status"></span>
<div id="txt"></div>
<script>
const btn=document.getElementById('btn'), statusEl=document.getElementById('status'), txt=document.getElementById('txt');
let ws, capCtx, playCtx, proc, src, stream, sink, playHead=0, on=false;

function playPCM(int16){
  if(!playCtx){ playCtx=new AudioContext({sampleRate:24000}); playHead=playCtx.currentTime; }
  const f32=new Float32Array(int16.length);
  for(let i=0;i<int16.length;i++) f32[i]=int16[i]/32768;
  const buf=playCtx.createBuffer(1,f32.length,24000); buf.getChannelData(0).set(f32);
  const s=playCtx.createBufferSource(); s.buffer=buf; s.connect(playCtx.destination);
  const t=Math.max(playCtx.currentTime, playHead); s.start(t); playHead=t+buf.duration;
}

async function start(){
  ws=new WebSocket((location.origin.replace(/^http/,'ws'))+'/ws');
  ws.binaryType='arraybuffer';
  ws.onmessage=(e)=>{
    if(typeof e.data==='string'){ const m=JSON.parse(e.data);
      if(m.type==='text'){ txt.textContent+=m.text; txt.scrollTop=txt.scrollHeight; }
      else if(m.type==='error'){ statusEl.textContent='error: '+m.text; }
    } else { playPCM(new Int16Array(e.data)); }
  };
  ws.onopen=async ()=>{
    stream=await navigator.mediaDevices.getUserMedia({audio:true});
    capCtx=new AudioContext({sampleRate:24000});
    src=capCtx.createMediaStreamSource(stream);
    proc=capCtx.createScriptProcessor(2048,1,1);
    sink=capCtx.createGain(); sink.gain.value=0;          // avoid mic echo
    src.connect(proc); proc.connect(sink); sink.connect(capCtx.destination);
    proc.onaudioprocess=(e)=>{
      if(!ws||ws.readyState!==1) return;
      const f32=e.inputBuffer.getChannelData(0);
      const i16=new Int16Array(f32.length);
      for(let i=0;i<f32.length;i++){ const s=Math.max(-1,Math.min(1,f32[i])); i16[i]=s<0?s*0x8000:s*0x7FFF; }
      ws.send(i16.buffer);
    };
    statusEl.textContent='listening — speak now';
  };
}
function stop(){
  if(proc)proc.disconnect(); if(src)src.disconnect();
  if(stream)stream.getTracks().forEach(t=>t.stop());
  if(ws){ try{ws.send('stop');}catch(e){} ws.close(); }
  statusEl.textContent='stopped';
}
btn.onclick=()=>{ on=!on; btn.classList.toggle('on',on); btn.textContent=on?'Stop':'Start conversation'; on?start():stop(); };
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Serve the full-duplex S2S demo page."""
    return _PAGE
