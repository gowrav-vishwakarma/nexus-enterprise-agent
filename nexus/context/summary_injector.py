"""Inject rolling conversation summary into system prompts when templates omit Jinja blocks."""

from nexus.config.context_summary import ContextSummaryConfig

_SUMMARY_HEADING = "## Conversation Summary"


class SummaryPromptInjector:
    """Appends session summary_text to the system prompt (RCS-style fallback)."""

    @staticmethod
    def inject(
        system_message: str,
        summary_text: str,
        summary_cfg: ContextSummaryConfig | None,
    ) -> str:
        """Append summary when injection is enabled and template lacks the block."""
        if not summary_cfg or summary_cfg.summarize_on is None or not summary_cfg.inject_into_prompt:
            return system_message
        if not summary_text or not summary_text.strip():
            return system_message
        if _SUMMARY_HEADING in system_message:
            return system_message

        block = f"{_SUMMARY_HEADING}\n{summary_text.strip()}"
        if system_message:
            return f"{system_message.rstrip()}\n\n{block}"
        return block
