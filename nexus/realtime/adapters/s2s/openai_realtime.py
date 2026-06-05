"""OpenAI Realtime (GA) speech-to-speech adapter.

Connects to the Realtime API over WebSocket, configures the session with the
agent's instructions and bridged tools, streams audio, and handles function
calls by executing Nexus tools and returning their output to the model.

Requires the ``websockets`` package (``realtime`` extra). Audio in/out is PCM16.
This adapter targets the GA event shapes (``response.output_audio.delta``,
``response.output_text.delta``, ``response.function_call_arguments.done``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, AsyncIterator

from nexus.realtime.adapters.s2s.base import SpeechToSpeechAdapter
from nexus.realtime.events import RealtimeStreamEvent

logger = logging.getLogger(__name__)


class OpenAIRealtimeS2S(SpeechToSpeechAdapter):
    """Speech-to-speech via OpenAI's Realtime API."""

    def _url(self) -> str:
        base = (self.config.base_url or "wss://api.openai.com/v1/realtime").rstrip("/")
        if base.startswith("http"):
            base = base.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}?model={self.config.model}"

    def _session_config(self) -> dict[str, Any]:
        """Build the session.update payload (instructions, voice, tools)."""
        tools = [
            {
                "type": "function",
                "name": s["name"],
                "description": s.get("description", ""),
                "parameters": s.get("parameters", {"type": "object", "properties": {}}),
            }
            for s in self.tool_schemas
        ]
        session: dict[str, Any] = {
            "type": "realtime",
            "instructions": self.instructions or "",
            "audio": {"output": {"voice": self.config.voice or "marin"}},
        }
        if tools:
            session["tools"] = tools
        return session

    async def _connect(self):
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "OpenAI Realtime S2S requires 'websockets'. Install with "
                "pip install nexus-enterprise-agent[realtime]"
            ) from exc

        from nexus.realtime.reconnect import connect_with_retry

        headers = {"Authorization": f"Bearer {self.config.get_api_key()}"}
        max_retries = int(self.config.extra.get("max_retries", 3))

        async def _open():
            ws = await websockets.connect(self._url(), additional_headers=headers)
            await ws.send(
                json.dumps({"type": "session.update", "session": self._session_config()})
            )
            return ws

        return await connect_with_retry(_open, max_retries=max_retries)

    async def _pump_events(self, ws) -> AsyncIterator[RealtimeStreamEvent]:
        """Translate provider events into RealtimeStreamEvents, bridging tools."""
        final_text_parts: list[str] = []

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type", "")

            if mtype in ("response.output_audio.delta", "response.audio.delta"):
                audio_b64 = msg.get("delta") or msg.get("audio")
                if audio_b64:
                    yield RealtimeStreamEvent.audio_chunk(base64.b64decode(audio_b64))
            elif mtype in (
                "response.output_audio_transcript.delta",
                "response.audio_transcript.delta",
            ):
                if msg.get("delta"):
                    yield RealtimeStreamEvent.transcript(msg["delta"], final=False)
            elif mtype in ("response.output_text.delta", "response.text.delta"):
                delta = msg.get("delta", "")
                if delta:
                    final_text_parts.append(delta)
                    yield RealtimeStreamEvent.text_delta(delta)
            elif mtype == "conversation.item.input_audio_transcription.completed":
                if msg.get("transcript"):
                    yield RealtimeStreamEvent.transcript(msg["transcript"], final=True)
            elif mtype == "response.function_call_arguments.done":
                call_id = msg.get("call_id", "")
                name = msg.get("name", "")
                try:
                    args = json.loads(msg.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield RealtimeStreamEvent(
                    event_type="tool_call", data={"tool_name": name, "tool_args": args, "call_id": call_id}
                )
                result = await self._execute_tool(name, args)
                yield RealtimeStreamEvent(event_type="tool_result", content=result, data={"tool_name": name})
                await ws.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": result,
                            },
                        }
                    )
                )
                await ws.send(json.dumps({"type": "response.create"}))
            elif mtype == "response.done":
                yield RealtimeStreamEvent(
                    event_type="final_response", content="".join(final_text_parts) or None
                )
                return
            elif mtype == "error":
                yield RealtimeStreamEvent(
                    event_type="error", content=str(msg.get("error")), data=msg.get("error")
                )
                return

    async def run_text(self, text: str) -> AsyncIterator[RealtimeStreamEvent]:
        """Send a text turn and stream the spoken response."""
        ws = await self._connect()
        try:
            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": text}],
                        },
                    }
                )
            )
            await ws.send(json.dumps({"type": "response.create"}))
            async for event in self._pump_events(ws):
                yield event
        finally:
            await ws.close()

    async def run_audio(
        self, audio_in: AsyncIterator[bytes]
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Stream audio frames in and the spoken response out."""
        ws = await self._connect()

        async def _send_audio() -> None:
            async for chunk in audio_in:
                await ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                )
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await ws.send(json.dumps({"type": "response.create"}))

        send_task = asyncio.create_task(_send_audio())
        try:
            async for event in self._pump_events(ws):
                yield event
        finally:
            send_task.cancel()
            await ws.close()
