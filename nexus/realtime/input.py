"""Multimodal user input models shared by realtime pipelines and channels.

These types let an agent receive more than a plain string: text, images, and
audio can all arrive in a single ``UserInput``. The text path is unchanged --
``UserInput.from_text("hi")`` behaves exactly like passing ``"hi"`` today.
"""

from __future__ import annotations

import base64
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class TextPart(BaseModel):
    """A plain text fragment of a multimodal message."""

    type: Literal["text"] = "text"
    text: str


class ImageUrlPart(BaseModel):
    """An image referenced by URL (sent to vision-capable LLMs as image_url)."""

    type: Literal["image_url"] = "image_url"
    url: str
    detail: Literal["auto", "low", "high"] = "auto"


class ImageBase64Part(BaseModel):
    """An inline image encoded as base64 with a MIME type."""

    type: Literal["image_base64"] = "image_base64"
    data: str = Field(..., description="Base64-encoded image bytes (no data: prefix)")
    mime_type: str = Field(default="image/png", description="e.g. image/png, image/jpeg")
    detail: Literal["auto", "low", "high"] = "auto"

    @classmethod
    def from_bytes(
        cls, raw: bytes, mime_type: str = "image/png", detail: str = "auto"
    ) -> "ImageBase64Part":
        """Build an inline image part from raw bytes."""
        return cls(
            data=base64.b64encode(raw).decode("ascii"),
            mime_type=mime_type,
            detail=detail,  # type: ignore[arg-type]
        )

    def to_data_url(self) -> str:
        """Render as a data: URL usable by OpenAI-style image_url fields."""
        return f"data:{self.mime_type};base64,{self.data}"


class AudioPart(BaseModel):
    """An audio attachment (e.g. a voice note) to be transcribed by STT.

    Audio is not sent to text LLMs directly; the pipeline/channel transcribes it
    first and the transcript becomes a ``TextPart``.
    """

    type: Literal["audio"] = "audio"
    data: str = Field(..., description="Base64-encoded audio bytes (no data: prefix)")
    mime_type: str = Field(default="audio/wav", description="e.g. audio/wav, audio/ogg")
    sample_rate: Optional[int] = Field(default=None, description="Sample rate in Hz if known")

    @classmethod
    def from_bytes(
        cls, raw: bytes, mime_type: str = "audio/wav", sample_rate: Optional[int] = None
    ) -> "AudioPart":
        """Build an audio part from raw bytes."""
        return cls(
            data=base64.b64encode(raw).decode("ascii"),
            mime_type=mime_type,
            sample_rate=sample_rate,
        )

    def to_bytes(self) -> bytes:
        """Decode the base64 payload back to raw bytes."""
        return base64.b64decode(self.data)


ContentPart = Union[TextPart, ImageUrlPart, ImageBase64Part, AudioPart]


class UserInput(BaseModel):
    """A multimodal message from the user.

    A message is a list of parts. Use the ``from_*`` constructors for the common
    cases, or build a list of parts directly for mixed content.
    """

    parts: list[ContentPart] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_text(cls, text: str, **metadata: Any) -> "UserInput":
        """Create a text-only input (equivalent to the legacy string path)."""
        return cls(parts=[TextPart(text=text)], metadata=metadata)

    @classmethod
    def from_image_url(
        cls, url: str, text: str = "", detail: str = "auto", **metadata: Any
    ) -> "UserInput":
        """Create an input with one image URL and optional caption text."""
        parts: list[ContentPart] = []
        if text:
            parts.append(TextPart(text=text))
        parts.append(ImageUrlPart(url=url, detail=detail))  # type: ignore[arg-type]
        return cls(parts=parts, metadata=metadata)

    @classmethod
    def from_image_bytes(
        cls,
        raw: bytes,
        text: str = "",
        mime_type: str = "image/png",
        **metadata: Any,
    ) -> "UserInput":
        """Create an input with one inline image and optional caption text."""
        parts: list[ContentPart] = []
        if text:
            parts.append(TextPart(text=text))
        parts.append(ImageBase64Part.from_bytes(raw, mime_type=mime_type))
        return cls(parts=parts, metadata=metadata)

    def to_text(self) -> str:
        """Concatenate all text parts (used as the LLM user_message string)."""
        return " ".join(p.text for p in self.parts if isinstance(p, TextPart)).strip()

    def text_parts(self) -> list[TextPart]:
        """Return only the text parts."""
        return [p for p in self.parts if isinstance(p, TextPart)]

    def image_parts(self) -> list[ContentPart]:
        """Return only the image parts (url or base64)."""
        return [p for p in self.parts if isinstance(p, (ImageUrlPart, ImageBase64Part))]

    def audio_parts(self) -> list[AudioPart]:
        """Return only the audio parts."""
        return [p for p in self.parts if isinstance(p, AudioPart)]

    def has_images(self) -> bool:
        """True if any image parts are present."""
        return bool(self.image_parts())

    def has_audio(self) -> bool:
        """True if any audio parts are present."""
        return bool(self.audio_parts())
