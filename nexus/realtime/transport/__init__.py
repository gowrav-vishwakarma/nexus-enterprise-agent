"""Realtime transports: how audio/events move between client and pipeline."""

from nexus.realtime.transport.base import Transport
from nexus.realtime.transport.memory import InMemoryTransport

__all__ = ["Transport", "InMemoryTransport"]


def __getattr__(name: str):
    """Lazily expose transports that may pull optional deps."""
    if name == "WebSocketTransport":
        from nexus.realtime.transport.websocket import WebSocketTransport

        return WebSocketTransport
    if name == "TwilioMediaStreamTransport":
        from nexus.realtime.transport.sip import TwilioMediaStreamTransport

        return TwilioMediaStreamTransport
    if name == "LiveKitTransport":
        from nexus.realtime.transport.webrtc import LiveKitTransport

        return LiveKitTransport
    raise AttributeError(f"module 'nexus.realtime.transport' has no attribute {name!r}")
