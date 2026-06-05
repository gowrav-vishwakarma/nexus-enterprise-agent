"""Browser voice demo (full-duplex) for the cascaded voice pipeline.

Serves a tiny web page that captures microphone audio, streams 16 kHz PCM16
frames to the realtime WebSocket, and renders the agent's transcript/replies.
Reuses the WebSocket endpoint from ``realtime_saas_api``.

Run:
    uv run --extra fastapi --extra realtime --extra openai \
        uvicorn examples.realtime_browser_voice:app --reload
Then open http://localhost:8000/ and allow microphone access.

With the default "mock" STT/TTS the page shows the event flow; set real
DEEPGRAM/OPENAI providers + keys (env or manifest) for actual speech.
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse

from examples.realtime_saas_api import app

_PAGE = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>NEXUS Voice</title>
<style>
 body{font-family:system-ui;margin:2rem;max-width:640px}
 #log{white-space:pre-wrap;border:1px solid #ccc;padding:1rem;height:300px;overflow:auto}
 button{padding:.6rem 1rem;font-size:1rem}
</style></head>
<body>
<h1>NEXUS Voice Assistant</h1>
<p>Full-duplex cascaded voice (VAD &rarr; STT &rarr; agent &rarr; TTS).</p>
<button id="start">Start talking</button>
<button id="stop" disabled>Stop</button>
<div id="log"></div>
<script>
const log = (m) => { const d=document.getElementById('log'); d.textContent += m+"\\n"; d.scrollTop=d.scrollHeight; };
let ws, ctx, proc, src, stream;

async function start() {
  const res = await fetch('/v1/realtime/sessions', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({agent:'voice_assistant'})});
  const info = await res.json();
  log('session: '+info.session_id);
  ws = new WebSocket(info.ws_url.replace(location.origin.replace(/^http/,'ws'), location.origin.replace(/^http/,'ws')));
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (typeof e.data === 'string') {
      const ev = JSON.parse(e.data);
      if (ev.event_type === 'transcript_final') log('you: '+ev.content);
      else if (ev.event_type === 'content') log('agent: '+ev.content);
      else if (ev.event_type === 'final_response') log('[done]');
      else if (ev.event_type === 'barge_in') log('[barge-in]');
    } else {
      log('[audio '+e.data.byteLength+' bytes]');
    }
  };
  ws.onopen = async () => {
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
    ctx = new AudioContext({sampleRate:16000});
    src = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096,1,1);
    src.connect(proc); proc.connect(ctx.destination);
    proc.onaudioprocess = (e) => {
      if (ws.readyState !== 1) return;
      const f32 = e.inputBuffer.getChannelData(0);
      const i16 = new Int16Array(f32.length);
      for (let i=0;i<f32.length;i++){ const s=Math.max(-1,Math.min(1,f32[i])); i16[i]=s<0?s*0x8000:s*0x7FFF; }
      ws.send(i16.buffer);
    };
    document.getElementById('start').disabled = true;
    document.getElementById('stop').disabled = false;
    log('listening...');
  };
}

function stop() {
  if (proc) proc.disconnect();
  if (src) src.disconnect();
  if (stream) stream.getTracks().forEach(t=>t.stop());
  if (ws) ws.close();
  document.getElementById('start').disabled = false;
  document.getElementById('stop').disabled = true;
  log('stopped');
}

document.getElementById('start').onclick = start;
document.getElementById('stop').onclick = stop;
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    """Serve the browser mic-capture demo page."""
    return _PAGE
