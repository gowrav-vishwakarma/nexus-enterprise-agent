"""Tests for Telegram + WhatsApp adapters and router vision/audio routing."""

import pytest

from nexus.channels.adapters.telegram import TelegramAdapter
from nexus.channels.adapters.whatsapp import WhatsAppAdapter
from nexus.channels.base import AgentOutput, InboundMessage
from nexus.channels.router import ChannelRouter
from nexus.realtime.input import ImageBase64Part, UserInput
from nexus.tools.context import RunContext


class _FakeResponse:
    def __init__(self, *, json_data=None, content=b""):
        self._json = json_data or {}
        self.content = content

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


class _FakeClient:
    """Records requests and returns scripted responses by URL substring."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.gets = []
        self.posts = []

    async def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return _FakeResponse()

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return _FakeResponse(json_data={"ok": True})


@pytest.mark.asyncio
async def test_telegram_parse_text():
    adapter = TelegramAdapter("TOKEN", http_client=_FakeClient())
    update = {"message": {"chat": {"id": 99}, "from": {"id": 42}, "text": "hello bot"}}
    msg = await adapter.parse_inbound(update)
    assert msg.channel == "telegram"
    assert msg.channel_user_id == "42"
    assert msg.channel_chat_id == "99"
    assert msg.user_input.to_text() == "hello bot"


@pytest.mark.asyncio
async def test_telegram_parse_photo_downloads_image():
    client = _FakeClient(
        routes={
            "getFile": _FakeResponse(json_data={"result": {"file_path": "photos/x.jpg"}}),
            "/file/bot": _FakeResponse(content=b"JPEGDATA"),
        }
    )
    adapter = TelegramAdapter("TOKEN", http_client=client)
    update = {
        "message": {
            "chat": {"id": 1},
            "from": {"id": 2},
            "caption": "look",
            "photo": [
                {"file_id": "small", "file_size": 100},
                {"file_id": "big", "file_size": 9999},
            ],
        }
    }
    msg = await adapter.parse_inbound(update)
    assert msg.user_input.has_images()
    assert msg.user_input.to_text() == "look"
    # Largest photo (by file_size) is selected.
    assert any("file_id" in str(g) or True for g in client.gets)
    assert client.gets[0][1]["params"]["file_id"] == "big"


@pytest.mark.asyncio
async def test_telegram_send_reply_posts_message():
    client = _FakeClient()
    adapter = TelegramAdapter("TOKEN", http_client=client)
    message = InboundMessage(
        channel="telegram",
        channel_user_id="42",
        channel_chat_id="99",
        user_input=UserInput.from_text("hi"),
    )
    await adapter.send_reply(message, AgentOutput(text="reply!"))
    url, kwargs = client.posts[0]
    assert "sendMessage" in url
    assert kwargs["json"] == {"chat_id": "99", "text": "reply!"}


@pytest.mark.asyncio
async def test_whatsapp_parse_text_and_send():
    client = _FakeClient()
    adapter = WhatsAppAdapter("WATOKEN", "PHONE123", http_client=client)
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {"from": "15551230000", "type": "text", "text": {"body": "hey"}}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await adapter.parse_inbound(payload)
    assert msg.channel_user_id == "15551230000"
    assert msg.user_input.to_text() == "hey"

    await adapter.send_reply(msg, AgentOutput(text="hi there"))
    url, kwargs = client.posts[0]
    assert "PHONE123/messages" in url
    assert kwargs["json"]["text"]["body"] == "hi there"
    assert kwargs["headers"]["Authorization"] == "Bearer WATOKEN"


@pytest.mark.asyncio
async def test_whatsapp_parse_image_downloads_media():
    client = _FakeClient(
        routes={
            "/MEDIA1": _FakeResponse(json_data={"url": "https://cdn/media1"}),
            "media1": _FakeResponse(content=b"IMGBYTES"),
        }
    )
    adapter = WhatsAppAdapter("WATOKEN", "PHONE123", http_client=client)
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1555",
                                    "type": "image",
                                    "image": {"id": "MEDIA1", "caption": "see", "mime_type": "image/png"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msg = await adapter.parse_inbound(payload)
    assert msg.user_input.has_images()
    assert msg.user_input.to_text() == "see"


class _VisionExecutor:
    def __init__(self, ctx):
        self.ctx = ctx
        self.received = None

    async def run(self, user_input, session_id=None):
        self.received = user_input

        class R:
            final_response = "I see an image"

        return R()


class _ImageChannel:
    name = "img"
    kind = "messaging"

    def __init__(self):
        self.sent = []

    async def parse_inbound(self, raw):
        return InboundMessage(
            channel="img",
            channel_user_id="u1",
            user_input=UserInput(parts=[ImageBase64Part.from_bytes(b"img")]),
        )

    async def send_reply(self, message, output):
        self.sent.append(output)


@pytest.mark.asyncio
async def test_router_routes_images_to_vision_executor():
    channel = _ImageChannel()
    captured = []

    def vision_factory(ctx: RunContext):
        ex = _VisionExecutor(ctx)
        captured.append(ex)
        return ex

    def text_factory(ctx: RunContext):
        raise AssertionError("text executor should not be used for image input")

    router = ChannelRouter(channel, text_factory, vision_executor_factory=vision_factory)
    output = await router.handle({})
    assert output.text == "I see an image"
    assert isinstance(captured[0].received, UserInput)
    assert captured[0].received.has_images()
