"""Vision-aware context builder.

Subclasses :class:`~nexus.context.builder.ContextWindowBuilder` so that all RCS,
history, memory, and token-budget logic is reused unchanged. The only addition
is: when image parts are pending, the current user message is rendered as a
multimodal content array (text + images) instead of a plain string.
"""

from __future__ import annotations

from typing import Any, Optional

from nexus.context.builder import ContextWindowBuilder
from nexus.realtime.input import ContentPart, ImageBase64Part, ImageUrlPart


def content_parts_to_openai(text: str, image_parts: list[ContentPart]) -> list[dict[str, Any]]:
    """Render text + image parts into an OpenAI-style multimodal content array."""
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for part in image_parts:
        if isinstance(part, ImageUrlPart):
            blocks.append(
                {"type": "image_url", "image_url": {"url": part.url, "detail": part.detail}}
            )
        elif isinstance(part, ImageBase64Part):
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": part.to_data_url(), "detail": part.detail},
                }
            )
    return blocks


class VisionContextBuilder(ContextWindowBuilder):
    """Context builder that attaches pending image parts to the current message."""

    def __init__(self, event_emitter: Optional[Any] = None) -> None:
        super().__init__(event_emitter=event_emitter)
        self.pending_content_parts: list[ContentPart] = []

    async def build(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Build messages, converting the current user message to multimodal form."""
        messages = await super().build(*args, **kwargs)

        parts = self.pending_content_parts
        if not parts:
            return messages

        current_user_message = kwargs.get("current_user_message")
        if current_user_message is None and len(args) >= 3:
            current_user_message = args[2]

        # Only attach to the message we just added for this turn.
        if current_user_message:
            for msg in reversed(messages):
                if msg.get("role") == "user" and msg.get("content") == current_user_message:
                    msg["content"] = content_parts_to_openai(current_user_message, parts)
                    break
            # Parts are consumed once; later turns in the same run are text-only.
            self.pending_content_parts = []

        return messages
