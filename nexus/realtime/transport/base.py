"""Base transport interface for realtime sessions."""

from __future__ import annotations

import abc
from typing import AsyncIterator

from nexus.realtime.events import RealtimeStreamEvent


class Transport(abc.ABC):
    """Bidirectional media + event channel between a client and the pipeline.

    Inbound audio is consumed via ``receive_audio``; outbound audio and
    structured events are pushed via ``send_audio`` / ``send_event``.
    """

    @abc.abstractmethod
    def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield inbound audio frames from the client."""

    @abc.abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Send an outbound audio chunk to the client."""

    @abc.abstractmethod
    async def send_event(self, event: RealtimeStreamEvent) -> None:
        """Send a structured event to the client."""

    async def close(self) -> None:
        """Close the transport (optional)."""
        return None
