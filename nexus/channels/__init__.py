"""Channel abstraction: normalize any inbound source into agent input.

A channel is an I/O edge (browser, telephony, Telegram, WhatsApp, ...). It turns
provider-native payloads into :class:`UserInput` + :class:`RunContext` and turns
agent results back into channel-native replies. The agent loop is unchanged.
"""

from nexus.channels.base import (
    AgentOutput,
    ChannelAdapter,
    ChannelIdentityResolver,
    ChannelKind,
    InboundMessage,
    StaticIdentityResolver,
)
from nexus.channels.registry import ChannelRegistry
from nexus.channels.router import ChannelRouter

__all__ = [
    "AgentOutput",
    "ChannelAdapter",
    "ChannelIdentityResolver",
    "ChannelKind",
    "InboundMessage",
    "StaticIdentityResolver",
    "ChannelRegistry",
    "ChannelRouter",
    "TelegramAdapter",
    "WhatsAppAdapter",
]


def __getattr__(name: str):
    """Lazily expose concrete adapters (keep imports light)."""
    if name == "TelegramAdapter":
        from nexus.channels.adapters.telegram import TelegramAdapter

        return TelegramAdapter
    if name == "WhatsAppAdapter":
        from nexus.channels.adapters.whatsapp import WhatsAppAdapter

        return WhatsAppAdapter
    raise AttributeError(f"module 'nexus.channels' has no attribute {name!r}")
