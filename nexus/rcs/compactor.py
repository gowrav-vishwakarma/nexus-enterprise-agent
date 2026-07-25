"""Server compactor fallback for context window overflow."""

import logging
from typing import Any, Optional

from nexus.config.rcs import ServerCompactorConfig
from nexus.session.models import AgentSession, ToolCallRecord
from nexus.llm.proxy import LLMProxy
from nexus.llm.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class ServerCompactor:
    """Fallback compactor to compress oldest tool calls when context window overflows."""

    def __init__(
        self,
        config: ServerCompactorConfig,
        llm_proxy: LLMProxy,
        storage_adapter: Any,
        event_emitter: Optional[Any] = None,
    ):
        self.config = config
        self.llm_proxy = llm_proxy
        self.storage = storage_adapter
        self.event_emitter = event_emitter

    async def should_trigger(self, session: AgentSession, current_context_tokens: int) -> bool:
        """Check if the fallback compactor trigger conditions are met."""
        if not self.config.enabled:
            return False
        
        # Check if context tokens exceed trigger threshold
        if current_context_tokens < self.config.trigger_token_threshold:
            return False

        # Check if there are any unsummarized (tagged) TCs to compress
        has_unsummarized = any(
            tc.summarized_response is None
            for turn in session.turns
            for tc in turn.tool_calls
        )
        return has_unsummarized

    async def compact(self, session: AgentSession, current_turn_index: int) -> dict[str, Any]:
        """Perform fallback compaction on the oldest unsummarized TCs."""
        from nexus.events.models import NexusEvent, NexusEventType
        
        # Emit trigger event
        if self.event_emitter:
            await self.event_emitter.emit(
                NexusEvent(
                    event_type=NexusEventType.RCS_COMPACTOR_TRIGGERED,
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    turn_index=current_turn_index,
                    data={"threshold": self.config.trigger_token_threshold}
                )
            )

        # 1. Collect all unsummarized TCs, sorted by turn and timestamp (oldest first)
        unsummarized_tcs: list[tuple[ToolCallRecord, int]] = []
        for turn in session.turns:
            for tc in turn.tool_calls:
                if tc.summarized_response is None:
                    unsummarized_tcs.append((tc, turn.turn_index))

        # Sort by TC index to ensure chronological ordering
        unsummarized_tcs.sort(key=lambda item: item[0].tc_index)

        # Take the oldest N TCs
        target_tcs = unsummarized_tcs[:self.config.compact_oldest_n_tcs]
        if not target_tcs:
            return {"tcs_compacted": [], "tokens_saved": 0}

        logger.info("ServerCompactor: Compacting oldest %d tool calls", len(target_tcs))

        # Use configured compactor LLM or fall back to main agent LLM
        compactor_llm = self.llm_proxy
        if self.config.compactor_llm:
            compactor_llm = LLMProxy(self.config.compactor_llm)

        tcs_compacted = []
        tokens_saved = 0

        from nexus.config.defaults import DEFAULT_COMPACTOR_PROMPT

        prompt_tmpl = self.config.prompt_template or DEFAULT_COMPACTOR_PROMPT

        for tc, turn_idx in target_tcs:
            prompt = prompt_tmpl.format(
                tool_name=tc.tool_name,
                tool_input=str(tc.tool_input),
                raw_response=tc.raw_response,
            )

            # Call LLM to summarize
            try:
                response = await compactor_llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.config.max_tokens_per_summary or 150,
                )
                summary = response.content.strip() if response.content else "[]"
            except Exception as e:
                logger.error("ServerCompactor: LLM summarization failed for %s: %s", tc.tc_id, e)
                continue

            # Update TC record
            tc.summarized_response = summary
            tc.summarized_by_turn = current_turn_index
            if summary == "[]":
                tc.is_dropped = True

            # Save atomically to storage
            try:
                if hasattr(self.storage, "update_tc_summary"):
                    await self.storage.update_tc_summary(
                        session_id=session.session_id,
                        tc_id=tc.tc_id,
                        summarized_response=summary,
                        summarized_by_turn=current_turn_index,
                        scope=session.to_scope(),
                    )
            except Exception as e:
                logger.error("ServerCompactor: Failed to save summary to storage: %s", e)

            # Count savings (single token-count call, consistent with interceptor)
            summary_tokens = TokenCounter.count_string(summary) if not tc.is_dropped else 0
            saved = max(0, tc.tokens_raw - summary_tokens)
            tc.tokens_summarized = summary_tokens
            session.total_tokens_saved_by_rcs += saved
            tokens_saved += saved
            tcs_compacted.append(tc.tc_id)

        # Emit completion event (distinct from the trigger event)
        if self.event_emitter:
            from nexus.events.models import RCSCompactorCompletedEvent
            await self.event_emitter.emit(
                RCSCompactorCompletedEvent(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    turn_index=current_turn_index,
                    tcs_compacted=tcs_compacted,
                    tokens_saved=tokens_saved,
                )
            )

        return {"tcs_compacted": tcs_compacted, "tokens_saved": tokens_saved}
