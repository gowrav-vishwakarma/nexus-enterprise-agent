"""Base voice-activity-detection adapter interface."""

from __future__ import annotations

import abc
from enum import Enum
from typing import Optional

from nexus.realtime.config import VADConfig


class VADEvent(str, Enum):
    """Turn-taking events emitted by a VAD."""

    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"


class VADAdapter(abc.ABC):
    """Detect speech boundaries in a stream of PCM16 audio frames.

    ``process_frame`` is stateful: feed it fixed-size frames and it returns a
    :class:`VADEvent` at boundaries, or ``None`` while the state is unchanged.
    On ``SPEECH_END`` the accumulated utterance is available via ``take_utterance``.
    """

    def __init__(self, config: VADConfig) -> None:
        self.config = config

    @abc.abstractmethod
    def process_frame(self, frame: bytes) -> Optional[VADEvent]:
        """Process one audio frame; return a boundary event or None."""

    @abc.abstractmethod
    def take_utterance(self) -> bytes:
        """Return and clear the audio buffered since the last SPEECH_START."""

    @abc.abstractmethod
    def reset(self) -> None:
        """Reset all internal state."""
