"""WhatsApp Cloud API (Meta) channel adapter.

Normalizes WhatsApp webhook payloads (text, audio, image messages) into
:class:`~nexus.channels.base.InboundMessage` and sends replies via the Graph API.
Media is fetched in two steps (media id -> media url -> bytes), both authorized
with the access token.

The HTTP client is injectable for testing; otherwise an ``httpx.AsyncClient`` is
created lazily.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from nexus.channels.base import AgentOutput, InboundMessage
from nexus.realtime.input import AudioPart, ImageBase64Part, TextPart, UserInput

logger = logging.getLogger(__name__)


class WhatsAppAdapter:
    """Channel adapter for the WhatsApp Cloud API."""

    kind = "messaging"

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        *,
        name: str = "whatsapp",
        api_base: str = "https://graph.facebook.com",
        api_version: str = "v21.0",
        http_client: Optional[Any] = None,
        download_media: bool = True,
    ) -> None:
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.name = name
        self.api_base = api_base.rstrip("/")
        self.api_version = api_version
        self._client = http_client
        self.download_media = download_media

    async def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    @staticmethod
    def _first_message(raw: Any) -> dict[str, Any]:
        """Extract the first message object from a webhook payload."""
        try:
            value = raw["entry"][0]["changes"][0]["value"]
            messages = value.get("messages", [])
            return messages[0] if messages else {}
        except (KeyError, IndexError, TypeError):
            return {}

    async def parse_inbound(self, raw: Any) -> InboundMessage:
        """Map a WhatsApp webhook payload into an InboundMessage."""
        msg = self._first_message(raw)
        sender = str(msg.get("from", ""))
        msg_type = msg.get("type")
        parts: list[Any] = []

        if msg_type == "text":
            parts.append(TextPart(text=msg.get("text", {}).get("body", "")))
        elif msg_type == "audio" and self.download_media:
            media = msg.get("audio", {})
            data = await self._download_media(media.get("id"))
            if data:
                parts.append(
                    AudioPart.from_bytes(data, mime_type=media.get("mime_type", "audio/ogg"))
                )
        elif msg_type == "image" and self.download_media:
            media = msg.get("image", {})
            data = await self._download_media(media.get("id"))
            if data:
                parts.append(
                    ImageBase64Part.from_bytes(data, mime_type=media.get("mime_type", "image/jpeg"))
                )
            caption = media.get("caption")
            if caption:
                parts.insert(0, TextPart(text=caption))

        if not parts:
            parts.append(TextPart(text=""))

        return InboundMessage(
            channel=self.name,
            channel_user_id=sender,
            channel_chat_id=sender,
            user_input=UserInput(parts=parts),
            raw=raw,
        )

    async def _download_media(self, media_id: Optional[str]) -> Optional[bytes]:
        """Resolve a WhatsApp media id to bytes (media url lookup + download)."""
        if not media_id:
            return None
        try:
            client = await self._get_client()
            meta = await client.get(
                f"{self.api_base}/{self.api_version}/{media_id}", headers=self._auth
            )
            meta.raise_for_status()
            url = meta.json()["url"]
            data = await client.get(url, headers=self._auth)
            data.raise_for_status()
            return data.content
        except Exception as exc:  # pragma: no cover - network failure
            logger.warning("WhatsAppAdapter: failed to download media %s: %s", media_id, exc)
            return None

    async def send_reply(self, message: InboundMessage, output: AgentOutput) -> None:
        """Send a text reply via the WhatsApp Cloud API."""
        if not output.text:
            return
        client = await self._get_client()
        await client.post(
            f"{self.api_base}/{self.api_version}/{self.phone_number_id}/messages",
            headers=self._auth,
            json={
                "messaging_product": "whatsapp",
                "to": message.channel_user_id,
                "type": "text",
                "text": {"body": output.text},
            },
        )
