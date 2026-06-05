"""Fully offline voice agent against the self-hosted local-ai-stack servers.

The framework stays lean: it only sends HTTP to local, OpenAI-compatible model
servers (run separately from `local-ai-stack`). No paid APIs, no torch here.

  LLM : Ollama         http://localhost:11434/v1
  STT : faster-whisper http://localhost:8001/v1   (local-ai-stack)
  TTS : Kokoro         http://localhost:8002/v1   (local-ai-stack)

Usage:
  uv run python examples/realtime_local_voice.py --check        # probe endpoints
  uv run python examples/realtime_local_voice.py                # one text turn (LLM+TTS)
  uv run python examples/realtime_local_voice.py --wav in.wav   # voice turn (STT+LLM+TTS)
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.runtime import RealtimeRuntime
from nexus.tools.context import RunContext

MANIFEST = Path(__file__).parent / "orchestration" / "voice_local.yaml"


def _endpoints() -> dict[str, str]:
    return {
        "LLM (Ollama)": os.environ.get("NEXUS_LLM_BASE_URL", "http://localhost:11434/v1"),
        "STT (faster-whisper)": os.environ.get("NEXUS_STT_BASE_URL", "http://localhost:8001/v1"),
        "TTS (Kokoro)": os.environ.get("NEXUS_TTS_BASE_URL", "http://localhost:8002/v1"),
    }


def check() -> int:
    """Probe each local server's /models endpoint."""
    import httpx

    ok = True
    for label, base in _endpoints().items():
        try:
            r = httpx.get(f"{base.rstrip('/')}/models", timeout=5)
            good = r.status_code == 200
            print(f"  [{'OK ' if good else 'FAIL'}] {label}: {base} ({r.status_code})")
            ok &= good
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] {label}: {base} ({exc})")
            ok = False
    print("\n", "all reachable" if ok else "start the servers in local-ai-stack first")
    return 0 if ok else 1


async def run_turn(wav: str | None) -> None:
    manifest = OrchestrationManifest.load(str(MANIFEST))
    runtime = RealtimeRuntime.from_manifest(
        manifest, run_context=RunContext(session_id="local-voice")
    )
    pipeline = runtime.build_pipeline()

    if wav:
        audio = Path(wav).read_bytes()
        print(f"voice turn from {wav} ({len(audio)} bytes):")
        stream = pipeline.process_utterance(audio, session_id="local-voice", mime_type="audio/wav")
    else:
        text = "Hi! In one sentence, what can you help me with?"
        print(f"text turn: {text!r}")
        stream = pipeline.process_text(text, session_id="local-voice")

    audio_chunks: list[bytes] = []
    async for ev in stream:
        if ev.event_type in ("transcript_final", "transcript_partial"):
            print(f"  [stt] {ev.content!r}")
        elif ev.event_type in ("content", "final_response"):
            if ev.content:
                print(f"  [llm] {ev.content!r}")
        elif ev.event_type == "audio_out" and ev.audio:
            audio_chunks.append(ev.audio)
        elif ev.event_type == "error":
            print(f"  [error] {ev.data}")

    if audio_chunks:
        out = Path("local_voice_out.wav")
        # The TTS server returns encoded WAV bytes; save the spoken reply.
        out.write_bytes(b"".join(audio_chunks))
        print(f"  [tts] wrote {out} ({out.stat().st_size} bytes of spoken audio)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="probe local servers and exit")
    ap.add_argument("--wav", help="path to a WAV file for a full STT->LLM->TTS turn")
    args = ap.parse_args()
    if args.check:
        return check()
    asyncio.run(run_turn(args.wav))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
