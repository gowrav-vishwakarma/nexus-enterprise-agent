"""Telegram Bot API channel adapter.

Normalizes Telegram ``Update`` payloads (text, voice notes, photos) into
:class:`~nexus.channels.base.InboundMessage` and sends replies via the Bot API.
Voice notes arrive as :class:`AudioPart` (transcribed by the router's STT);
photos arrive as :class:`ImageBase64Part` (handled by a vision executor).

The HTTP client is injectable for testing; in production it lazily builds an
``httpx.AsyncClient``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from nexus.channels.base import AgentOutput, InboundMessage
from nexus.realtime.input import AudioPart, ImageBase64Part, UserInput

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Channel adapter for a Telegram bot."""

    kind = "messaging"

    def __init__(
        self,
        token: str,
        *,
        name: str = "telegram",
        api_base: str = "https://api.telegram.org",
        http_client: Optional[Any] = None,
        download_media: bool = True,
    ) -> None:
        self.token = token
        self.name = name
        self.api_base = api_base.rstrip("/")
        self._client = http_client
        self.download_media = download_media

    async def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    def _api(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    async def parse_inbound(self, raw: Any) -> InboundMessage:
        """Map a Telegram Update into an InboundMessage."""
        message = raw.get("message") or raw.get("edited_message") or {}
        chat = message.get("chat", {})
        sender = message.get("from", {})
        chat_id = str(chat.get("id", sender.get("id", "")))
        user_id = str(sender.get("id", chat_id))

        parts: list[Any] = []
        text = message.get("text") or message.get("caption")
        if text:
            from nexus.realtime.input import TextPart

            parts.append(TextPart(text=text))

        if self.download_media:
            voice = message.get("voice") or message.get("audio")
            if voice and voice.get("file_id"):
                audio = await self._download_file(voice["file_id"])
                if audio:
                    parts.append(
                        AudioPart.from_bytes(
                            audio, mime_type=voice.get("mime_type", "audio/ogg")
                        )
                    )

            photos = message.get("photo")
            if photos:
                largest = max(photos, key=lambda p: p.get("file_size", 0))
                image = await self._download_file(largest["file_id"])
                if image:
                    parts.append(ImageBase64Part.from_bytes(image, mime_type="image/jpeg"))

        if not parts:
            from nexus.realtime.input import TextPart

            parts.append(TextPart(text=""))

        return InboundMessage(
            channel=self.name,
            channel_user_id=user_id,
            channel_chat_id=chat_id,
            user_input=UserInput(parts=parts),
            raw=raw,
        )

    async def _download_file(self, file_id: str) -> Optional[bytes]:
        """Resolve a Telegram file_id to bytes via getFile + file download."""
        try:
            client = await self._get_client()
            resp = await client.get(self._api("getFile"), params={"file_id": file_id})
            resp.raise_for_status()
            file_path = resp.json()["result"]["file_path"]
            file_url = f"{self.api_base}/file/bot{self.token}/{file_path}"
            data = await client.get(file_url)
            data.raise_for_status()
            return data.content
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning("TelegramAdapter: failed to download %s: %s", file_id, exc)
            return None

    async def send_reply(self, message: InboundMessage, output: AgentOutput) -> None:
        """Send a text (and optional voice) reply back to the chat."""
        chat_id = message.channel_chat_id or message.channel_user_id
        client = await self._get_client()
        if output.text:
            await client.post(
                self._api("sendMessage"), json={"chat_id": chat_id, "text": output.text}
            )
        if output.audio:
            files = {"voice": ("reply.ogg", output.audio, output.audio_mime_type)}
            await client.post(
                self._api("sendVoice"), data={"chat_id": chat_id}, files=files
            )
