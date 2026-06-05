"""Core channel contracts shared by realtime and messaging channels."""

from __future__ import annotations

from typing import Any, AsyncIterator, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from nexus.realtime.input import UserInput
from nexus.tools.context import RunContext

ChannelKind = Literal["realtime", "messaging"]


class InboundMessage(BaseModel):
    """A normalized inbound message from any channel.

    The adapter maps a provider payload (a Telegram update, a WhatsApp webhook,
    a WebSocket frame) into this shape. ``channel_user_id`` is the provider's
    native id (chat id, phone number) used to resolve a stable Nexus identity.
    """

    channel: str = Field(..., description="Channel name, e.g. telegram_support")
    kind: ChannelKind = Field(default="messaging", description="realtime or messaging")
    channel_user_id: str = Field(..., description="Provider-native sender id (chat id, phone, ...)")
    channel_chat_id: Optional[str] = Field(
        default=None, description="Provider-native conversation id (defaults to user id)"
    )
    user_input: UserInput = Field(..., description="Normalized multimodal input")
    tenant_id: Optional[str] = Field(default=None, description="Resolved tenant, if known")
    raw: dict[str, Any] = Field(default_factory=dict, description="Original provider payload")

    model_config = {"arbitrary_types_allowed": True}


class AgentOutput(BaseModel):
    """A normalized agent reply to be rendered onto a channel."""

    text: Optional[str] = Field(default=None, description="Reply text")
    audio: Optional[bytes] = Field(default=None, exclude=True, description="Synthesized audio reply")
    audio_mime_type: str = Field(default="audio/mpeg", description="MIME type of audio reply")
    session_id: Optional[str] = Field(default=None, description="Session the reply belongs to")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Channel render hints")

    model_config = {"arbitrary_types_allowed": True}


@runtime_checkable
class ChannelAdapter(Protocol):
    """Protocol every channel adapter implements.

    ``kind`` declares whether the channel is realtime or messaging. Messaging
    channels use ``parse_inbound`` / ``send_reply``; realtime channels may also
    implement :class:`RealtimeTransport` for streaming media.
    """

    name: str
    kind: ChannelKind

    async def parse_inbound(self, raw: Any) -> InboundMessage:
        """Normalize a provider payload into an InboundMessage."""
        ...

    async def send_reply(self, message: InboundMessage, output: AgentOutput) -> None:
        """Render and deliver an agent reply over the channel."""
        ...


@runtime_checkable
class RealtimeTransport(Protocol):
    """Streaming media transport for realtime channels."""

    async def send_audio(self, chunk: bytes) -> None:
        """Push an outbound audio chunk to the client."""

    def receive_audio(self) -> AsyncIterator[bytes]:
        """Yield inbound audio chunks from the client."""

    async def send_event(self, event: Any) -> None:
        """Push a structured RealtimeStreamEvent to the client."""


class ChannelIdentityResolver(Protocol):
    """Map a channel-native identity to Nexus tenant/user/session."""

    def resolve(self, message: InboundMessage) -> RunContext:
        """Return a RunContext scoped to tenant/user/session for this message."""


class StaticIdentityResolver:
    """Default identity resolver.

    Maps the channel's native ids onto ``user_id`` and ``session_id`` and uses a
    fixed (or message-provided) tenant. Suitable for single-tenant bots; SaaS
    deployments supply their own resolver to look up the tenant per channel.
    """

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        *,
        session_prefix: str = "",
    ) -> None:
        self.tenant_id = tenant_id
        self.session_prefix = session_prefix

    def resolve(self, message: InboundMessage) -> RunContext:
        """Build a deterministic RunContext from the inbound identity."""
        tenant_id = message.tenant_id or self.tenant_id
        chat_id = message.channel_chat_id or message.channel_user_id
        session_id = f"{self.session_prefix}{message.channel}_{chat_id}"
        return RunContext(
            tenant_id=tenant_id,
            user_id=f"{message.channel}:{message.channel_user_id}",
            session_id=session_id,
            metadata={"channel": message.channel, "channel_chat_id": chat_id},
        )
