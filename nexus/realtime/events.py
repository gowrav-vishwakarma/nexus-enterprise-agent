"""Realtime stream events emitted by voice/AV pipelines.

These mirror the text ``AgentStreamEvent`` but add voice-specific event types
(partial transcripts, outbound audio, barge-in, DTMF). Transports translate
these into wire frames; the agent loop itself stays text-based.
"""

from __future__ import annotations

import base64
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

RealtimeEventType = Literal[
    "session_started",
    "transcript_partial",
    "transcript_final",
    "content",
    "audio_out",
    "tool_call",
    "tool_result",
    "barge_in",
    "dtmf",
    "turn_end",
    "final_response",
    "error",
    "event",
]


class RealtimeStreamEvent(BaseModel):
    """An incremental event from a realtime (voice/AV) agent run.

    ``audio`` holds raw bytes for ``audio_out`` events and is excluded from JSON
    serialization; transports send it on the binary channel. Use ``audio_b64``
    when a JSON-only transport must carry audio inline.
    """

    event_type: RealtimeEventType = Field(..., description="Type of realtime event")
    content: Optional[str] = Field(default=None, description="Text payload (transcript or reply delta)")
    audio: Optional[bytes] = Field(default=None, exclude=True, description="Raw audio bytes (binary channel)")
    data: Optional[dict[str, Any]] = Field(default=None, description="Structured details")

    model_config = {"arbitrary_types_allowed": True}

    @property
    def audio_b64(self) -> Optional[str]:
        """Base64 of the audio payload for JSON-only transports."""
        if self.audio is None:
            return None
        return base64.b64encode(self.audio).decode("ascii")

    @classmethod
    def transcript(cls, text: str, *, final: bool, **data: Any) -> "RealtimeStreamEvent":
        """Build a transcript_partial / transcript_final event."""
        return cls(
            event_type="transcript_final" if final else "transcript_partial",
            content=text,
            data=data or None,
        )

    @classmethod
    def audio_chunk(cls, audio: bytes, **data: Any) -> "RealtimeStreamEvent":
        """Build an outbound audio event."""
        return cls(event_type="audio_out", audio=audio, data=data or None)

    @classmethod
    def text_delta(cls, text: str, **data: Any) -> "RealtimeStreamEvent":
        """Build a reply text delta event."""
        return cls(event_type="content", content=text, data=data or None)
