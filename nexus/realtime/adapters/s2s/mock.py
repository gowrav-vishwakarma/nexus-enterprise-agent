"""Mock speech-to-speech adapter for tests and local development.

Echoes input as a spoken reply and, when asked, exercises the tool bridge so the
end-to-end S2S + tools flow can be tested without a realtime provider.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from nexus.realtime.adapters.s2s.base import SpeechToSpeechAdapter
from nexus.realtime.events import RealtimeStreamEvent


class MockS2S(SpeechToSpeechAdapter):
    """Deterministic S2S adapter.

    If the text starts with ``TOOL:plugin.tool {json-args}`` it invokes the tool
    bridge and speaks the result; otherwise it echoes the input.
    """

    async def run_text(self, text: str) -> AsyncIterator[RealtimeStreamEvent]:
        """Process one text turn deterministically."""
        yield RealtimeStreamEvent.transcript(text, final=True)

        if text.startswith("TOOL:"):
            spec = text[len("TOOL:") :].strip()
            name, _, arg_str = spec.partition(" ")
            try:
                args = json.loads(arg_str) if arg_str else {}
            except json.JSONDecodeError:
                args = {}
            yield RealtimeStreamEvent(event_type="tool_call", data={"tool_name": name, "tool_args": args})
            result = await self._execute_tool(name, args)
            yield RealtimeStreamEvent(event_type="tool_result", content=result, data={"tool_name": name})
            reply = f"Tool says: {result}"
        else:
            reply = f"echo: {text}"

        yield RealtimeStreamEvent.text_delta(reply)
        yield RealtimeStreamEvent.audio_chunk(b"AUDIO:" + reply.encode("utf-8"), text=reply)
        yield RealtimeStreamEvent(event_type="final_response", content=reply)

    async def run_audio(
        self, audio_in: AsyncIterator[bytes]
    ) -> AsyncIterator[RealtimeStreamEvent]:
        """Decode buffered audio as UTF-8 text then process as a text turn."""
        chunks: list[bytes] = []
        async for chunk in audio_in:
            chunks.append(chunk)
        try:
            text = b"".join(chunks).decode("utf-8").strip()
        except UnicodeDecodeError:
            text = f"[{sum(len(c) for c in chunks)} bytes of audio]"
        async for ev in self.run_text(text):
            yield ev
