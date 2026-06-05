"""Tests for the channel abstraction (contracts, router, identity)."""

import pytest

from nexus.channels import (
    AgentOutput,
    ChannelRegistry,
    ChannelRouter,
    InboundMessage,
    StaticIdentityResolver,
)
from nexus.realtime.input import AudioPart, UserInput
from nexus.tools.context import RunContext


class _FakeResult:
    def __init__(self, text: str, session_id: str) -> None:
        self.final_response = text
        self.session_id = session_id


class _FakeExecutor:
    def __init__(self, run_context: RunContext) -> None:
        self.run_context = run_context
        self.received: list[str] = []

    async def run(self, user_message: str, *, session_id=None):
        self.received.append(user_message)
        return _FakeResult(f"echo: {user_message}", session_id or "s")


class _FakeChannel:
    name = "fake"
    kind = "messaging"

    def __init__(self) -> None:
        self.sent: list[AgentOutput] = []

    async def parse_inbound(self, raw) -> InboundMessage:
        return InboundMessage(
            channel=self.name,
            channel_user_id=raw["from"],
            user_input=UserInput.from_text(raw["text"]),
            raw=raw,
        )

    async def send_reply(self, message: InboundMessage, output: AgentOutput) -> None:
        self.sent.append(output)


class _FakeSTT:
    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        return "transcribed words"


def test_static_identity_resolver():
    resolver = StaticIdentityResolver(tenant_id="acme")
    msg = InboundMessage(
        channel="telegram",
        channel_user_id="12345",
        user_input=UserInput.from_text("hi"),
    )
    ctx = resolver.resolve(msg)
    assert ctx.tenant_id == "acme"
    assert ctx.user_id == "telegram:12345"
    assert ctx.session_id == "telegram_12345"


def test_channel_registry():
    reg = ChannelRegistry()
    ch = _FakeChannel()
    reg.register(ch)
    assert reg.has("fake")
    assert reg.get("fake") is ch
    assert reg.names() == ["fake"]
    with pytest.raises(KeyError):
        reg.get("missing")


@pytest.mark.asyncio
async def test_router_text_message():
    channel = _FakeChannel()
    executors: list[_FakeExecutor] = []

    def factory(ctx: RunContext) -> _FakeExecutor:
        ex = _FakeExecutor(ctx)
        executors.append(ex)
        return ex

    router = ChannelRouter(
        channel,
        factory,
        identity_resolver=StaticIdentityResolver(tenant_id="acme"),
    )
    output = await router.handle({"from": "u1", "text": "hello"})
    assert output.text == "echo: hello"
    assert channel.sent[0].text == "echo: hello"
    assert executors[0].received == ["hello"]


@pytest.mark.asyncio
async def test_router_transcribes_audio_note():
    channel = _FakeChannel()

    async def parse(raw):
        return InboundMessage(
            channel="fake",
            channel_user_id="u2",
            user_input=UserInput(parts=[AudioPart.from_bytes(b"audio")]),
            raw=raw,
        )

    channel.parse_inbound = parse  # type: ignore[assignment]

    captured: list[_FakeExecutor] = []

    def factory(ctx: RunContext) -> _FakeExecutor:
        ex = _FakeExecutor(ctx)
        captured.append(ex)
        return ex

    router = ChannelRouter(channel, factory, stt=_FakeSTT())
    await router.handle({"voice": True})
    assert captured[0].received == ["transcribed words"]
