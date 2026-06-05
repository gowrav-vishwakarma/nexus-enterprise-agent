"""Context summarizer: folds oldest chat turns into rolling summary_text."""

from __future__ import annotations

import logging
from typing import Any, Optional

from nexus.config.context_summary import ContextSummaryConfig
from nexus.llm.proxy import LLMProxy
from nexus.session.models import AgentSession, TurnRecord

logger = logging.getLogger(__name__)


class ContextSummarizer:
    """Folds oldest unfoldable turns into session.summary_text when context is full."""

    def __init__(
        self,
        config: ContextSummaryConfig,
        llm_proxy: LLMProxy,
        session_manager: Any,
        event_emitter: Any = None,
    ):
        self.config = config
        self.llm_proxy = llm_proxy
        self.session_manager = session_manager
        self.event_emitter = event_emitter

    @property
    def active(self) -> bool:
        return self.config.summarize_on is not None

    def _foldable_turns(self, session: AgentSession) -> list[TurnRecord]:
        """Turns not yet folded into summary_text, oldest first."""
        cutoff = session.summary_through_turn
        candidates = [t for t in session.turns if t.turn_index > cutoff]
        candidates.sort(key=lambda t: t.turn_index)
        return candidates

    def should_trigger(
        self,
        session: AgentSession,
        current_tokens: int,
        context_window_tokens: int,
    ) -> bool:
        if not self.active or context_window_tokens <= 0:
            return False
        ratio = current_tokens / context_window_tokens
        if ratio < self.config.summarize_on:
            return False
        return len(self._foldable_turns(session)) >= 1

    def _build_turns_digest(self, turns: list[TurnRecord]) -> str:
        lines: list[str] = []
        for turn in turns:
            if turn.user_message:
                lines.append(f"User: {turn.user_message}")
            for msg in turn.llm_messages:
                if msg.get("role") == "assistant" and msg.get("content"):
                    lines.append(f"Assistant: {msg['content']}")
        return "\n".join(lines)

    async def summarize(self, session: AgentSession, turn_index: int) -> str:
        """Fold oldest unfoldable turns into summary_text and remove them from session."""
        if not self.active:
            return session.summary_text

        foldable = self._foldable_turns(session)
        if not foldable:
            return session.summary_text

        to_fold = foldable[: self.config.turns_to_fold]
        digest = self._build_turns_digest(to_fold)
        if not digest.strip():
            return session.summary_text

        proxy = self.llm_proxy
        if self.config.summary_llm is not None:
            proxy = LLMProxy(self.config.summary_llm)

        prompt = (
            self.config.get_summary_prompt()
            .replace("{existing_summary}", session.summary_text or "")
            .replace("{turns_to_summarize}", digest)
        )

        try:
            response = await proxy.chat(messages=[{"role": "user", "content": prompt}])
            new_part = (response.content or "").strip()
        except Exception as exc:
            logger.warning("ContextSummarizer: summarization failed, skipping: %s", exc)
            return session.summary_text

        if not new_part:
            return session.summary_text

        if session.summary_text:
            merged = f"{session.summary_text.rstrip()}\n\n{new_part}"
        else:
            merged = new_part
        session.summary_text = merged[: self.config.max_summary_chars]

        folded_indices = {t.turn_index for t in to_fold}
        session.turns = [t for t in session.turns if t.turn_index not in folded_indices]
        session.summary_through_turn = max(session.summary_through_turn, max(folded_indices))

        await self.session_manager.save_session(session)
        await self._emit_event(session, turn_index, to_fold, folded_indices)

        return session.summary_text

    async def _emit_event(
        self,
        session: AgentSession,
        turn_index: int,
        folded_turns: list[TurnRecord],
        folded_indices: set[int],
    ) -> None:
        if not self.event_emitter:
            return
        from nexus.events.models import NexusEvent, NexusEventType

        await self.event_emitter.emit(
            NexusEvent(
                event_type=NexusEventType.CONTEXT_SUMMARIZED,
                session_id=session.session_id,
                agent_id=session.agent_id,
                turn_index=turn_index,
                data={
                    "folded_turn_indices": sorted(folded_indices),
                    "summary_length": len(session.summary_text),
                    "turns_folded": len(folded_turns),
                },
            )
        )
