"""Prompts for the voice_grpc example agent.

The manifest (``voice_grpc.yaml``) references ``voice_system`` via
``persona.prompt``. Prompts may be plain strings (Jinja templates rendered at
run time) or callables that receive persona/run-context values and return a
template string. Here we use a callable so the assistant knows today's date
without needing a tool call for simple cases.
"""

from __future__ import annotations

from datetime import datetime


def voice_system(role: str | None = None, goal: str | None = None, **_: object) -> str:
    """Build the voice assistant system prompt."""
    today = datetime.now().strftime("%A, %d %B %Y")
    role = role or "Voice Assistant"
    goal = goal or "Have a natural spoken conversation."
    return f"""You are {role}. {goal}

Guidelines:
- Reply in the same language the user speaks (Hindi or English).
- Keep answers short and conversational — they are spoken aloud, not read.
- Never use markdown, bullet points, emojis, or code blocks.
- When the user asks about the current time or date, call the matching tool
  instead of guessing.

Today's date is {today}.
"""


PROMPTS: dict = {
    "voice_system": voice_system,
}
