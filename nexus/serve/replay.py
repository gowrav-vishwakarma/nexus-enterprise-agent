"""Replay buffer so a dropped stream can reattach without re-running the agent.

A browser that loses its connection mid-run would otherwise either lose the rest
of the answer or have to resend the message and pay for a second run. The server
keeps each run's events in a bounded buffer, and the client reconnects with the
sequence number it last saw.

The buffer is per-process and in memory. Behind more than one worker, either pin a
session to a worker or supply a shared implementation with the same two methods.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, AsyncIterator, Optional


class _SessionBuffer:
    """Events for one run, plus a signal for readers waiting on more."""

    def __init__(self, max_events: int) -> None:
        self.events: deque[tuple[int, dict[str, Any]]] = deque(maxlen=max_events)
        self.done = False
        self.updated_at = time.monotonic()
        self._new_data = asyncio.Event()

    def append(self, seq: int, payload: dict[str, Any]) -> None:
        self.events.append((seq, payload))
        self.updated_at = time.monotonic()
        self._new_data.set()

    def finish(self) -> None:
        self.done = True
        self.updated_at = time.monotonic()
        self._new_data.set()

    async def wait(self) -> None:
        await self._new_data.wait()
        self._new_data.clear()


class StreamReplayBuffer:
    """Bounded, scope-keyed store of recent stream events.

    Args:
        max_events_per_session: Events retained per run. Older events are dropped,
            so a client that reconnects too late sees a gap rather than unbounded
            memory growth.
        ttl_seconds: How long a finished run stays available to reattach to.
    """

    def __init__(self, *, max_events_per_session: int = 500, ttl_seconds: float = 900.0):
        self.max_events_per_session = max_events_per_session
        self.ttl_seconds = ttl_seconds
        self._buffers: dict[str, _SessionBuffer] = {}

    def _get(self, key: str, *, create: bool = False) -> Optional[_SessionBuffer]:
        self._prune()
        buffer = self._buffers.get(key)
        if buffer is None and create:
            buffer = _SessionBuffer(self.max_events_per_session)
            self._buffers[key] = buffer
        return buffer

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        for key in [k for k, b in self._buffers.items() if b.updated_at < cutoff]:
            del self._buffers[key]

    def start(self, key: str) -> None:
        """Begin (or restart) buffering for a run, discarding any previous one."""
        self._prune()
        self._buffers[key] = _SessionBuffer(self.max_events_per_session)

    def append(self, key: str, seq: int, payload: dict[str, Any]) -> None:
        buffer = self._get(key, create=True)
        assert buffer is not None
        buffer.append(seq, payload)

    def finish(self, key: str) -> None:
        buffer = self._get(key)
        if buffer is not None:
            buffer.finish()

    def has(self, key: str) -> bool:
        return self._get(key) is not None

    def earliest_seq(self, key: str) -> Optional[int]:
        """Lowest sequence still retained, or None when nothing is buffered."""
        buffer = self._get(key)
        if buffer is None or not buffer.events:
            return None
        return buffer.events[0][0]

    async def replay(self, key: str, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Yield buffered events after *after_seq*, then follow the run until it ends.

        Raises:
            KeyError: The run is unknown or has aged out of the buffer.
        """
        buffer = self._get(key)
        if buffer is None:
            raise KeyError(key)

        cursor = after_seq
        while True:
            pending = [(s, p) for s, p in list(buffer.events) if s > cursor]
            for seq, payload in pending:
                cursor = seq
                yield payload
            if buffer.done:
                return
            await buffer.wait()


async def buffered_stream(
    events: AsyncIterator[Any],
    buffer: StreamReplayBuffer,
    key: str,
) -> AsyncIterator[tuple[int, dict[str, Any]]]:
    """Record each event as it streams, yielding ``(seq, payload)``.

    Sequence numbers come from the runner (`event.data["seq"]`), so a replayed
    event carries the same number the client originally saw.
    """
    buffer.start(key)
    try:
        fallback_seq = 0
        async for event in events:
            payload = event.model_dump(mode="json")
            fallback_seq += 1
            seq = (payload.get("data") or {}).get("seq", fallback_seq)
            buffer.append(key, seq, payload)
            yield seq, payload
    finally:
        buffer.finish(key)
