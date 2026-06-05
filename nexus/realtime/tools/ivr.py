"""IVR (interactive voice response) tool plugin for half-duplex voice agents.

These tools let an LLM drive a phone menu: play prompts, collect DTMF key
presses, transfer, or hang up. Tools record their intent in ``RunContext.metadata``
so the active transport (WebSocket/SIP) can execute the side effects. DTMF the
caller has pressed is read from ``RunContext.metadata['dtmf_buffer']``.
"""

from typing import Optional

from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin


@tool_plugin(name="ivr_menu")
class IVRMenuPlugin:
    """Tools for menu-driven, half-duplex telephony agents."""

    @tool(
        name="play_prompt",
        description="Speak a prompt to the caller (queued for TTS playback).",
    )
    def play_prompt(self, text: str, run_context: RunContext) -> str:
        """Queue a spoken prompt for the caller."""
        actions = run_context.metadata.setdefault("ivr_actions", [])
        actions.append({"action": "play_prompt", "text": text})
        return f"Prompt queued: {text!r}"

    @tool(
        name="collect_dtmf",
        description=(
            "Collect DTMF digits the caller presses. Returns the digits captured "
            "so far. Use num_digits to limit, or 0 for variable length ending in #."
        ),
    )
    def collect_dtmf(
        self,
        run_context: RunContext,
        num_digits: int = 1,
        prompt: Optional[str] = None,
    ) -> str:
        """Return the DTMF digits collected from the caller."""
        if prompt:
            actions = run_context.metadata.setdefault("ivr_actions", [])
            actions.append({"action": "play_prompt", "text": prompt})
        run_context.metadata["dtmf_expected"] = num_digits
        buffer = str(run_context.metadata.get("dtmf_buffer", ""))
        if not buffer:
            return "No digits pressed yet."
        captured = buffer if num_digits <= 0 else buffer[:num_digits]
        return f"Caller pressed: {captured}"

    @tool(
        name="transfer_call",
        description="Transfer the caller to another destination (agent/queue/number).",
    )
    def transfer_call(self, destination: str, run_context: RunContext) -> str:
        """Record a call-transfer action."""
        actions = run_context.metadata.setdefault("ivr_actions", [])
        actions.append({"action": "transfer", "destination": destination})
        run_context.metadata["ivr_terminal"] = True
        return f"Transferring caller to {destination}."

    @tool(
        name="hang_up",
        description="End the call. Optionally provide a goodbye reason.",
    )
    def hang_up(self, run_context: RunContext, reason: str = "") -> str:
        """Record a hang-up action."""
        actions = run_context.metadata.setdefault("ivr_actions", [])
        actions.append({"action": "hang_up", "reason": reason})
        run_context.metadata["ivr_terminal"] = True
        return "Call ended." + (f" ({reason})" if reason else "")
