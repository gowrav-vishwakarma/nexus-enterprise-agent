"""In-memory transport for tests and local simulation."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.transport.base import Transport


class InMemoryTransport(Transport):
    """Feed audio from a queue; capture outbound audio and events in lists."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self.sent_audio: list[bytes] = []
        self.sent_events: list[RealtimeStreamEvent] = []

    async def push_audio(self, chunk: bytes) -> None:
        """Enqueue an inbound audio frame (client -> pipeline)."""
        await self._inbound.put(chunk)

    async def end_input(self) -> None:
        """Signal end of inbound audio."""
        await self._inbound.put(None)

    async def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield queued inbound audio until end_input is signaled."""
        while True:
            chunk = await self._inbound.get()
            if chunk is None:
                return
            yield chunk

    async def send_audio(self, chunk: bytes) -> None:
        """Capture an outbound audio chunk."""
        self.sent_audio.append(chunk)

    async def send_event(self, event: RealtimeStreamEvent) -> None:
        """Capture an outbound event."""
        self.sent_events.append(event)
