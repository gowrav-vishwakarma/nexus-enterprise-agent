"""Context window builder for the Nexus Agent Framework."""

import copy
import json
import logging
from datetime import datetime
from typing import Any, Optional

from nexus.config.agent import AgentConfig
from nexus.context.memory_injector import MemoryPromptInjector
from nexus.context.rcs_injector import RCSSystemPromptInjector
from nexus.context.summary_injector import SummaryPromptInjector
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord
from nexus.tools.context import RunContext
from nexus.utils.jinja import render_system_prompt
from nexus.llm.content_tool_calls import EMPTY_ASSISTANT_PLACEHOLDER, sanitize_assistant_llm_message
from nexus.llm.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class ContextWindowBuilder:
    """Builds and manages the message sequence for the LLM context window."""

    def __init__(self, event_emitter: Optional[Any] = None):
        self.event_emitter = event_emitter

    @staticmethod
    def _format_tool_signature(tc: ToolCallRecord, include_signature: bool) -> str:
        """Render ``tool_name(arg=value, ...)`` for a tool call.

        Excludes the injected ``_context_updates`` RCS parameter so the LLM
        never sees it as part of the tool's own arguments.
        """
        if not include_signature:
            return ""
        args_str = ", ".join(
            f"{k}={json.dumps(v)}"
            for k, v in tc.tool_input.items()
            if k != "_context_updates"
        )
        return f"{tc.tool_name}({args_str})"

    @staticmethod
    def _summary_text(tc: ToolCallRecord) -> str:
        """Return the usable summary for a TC, or ``""`` when it has none.

        A missing, empty, whitespace-only, or legacy ``"[]"`` value all mean the
        same thing: this tool call is simply not summarized, so its full raw
        response is used. ``"[]"`` was written by older versions to mark a
        result as dropped; it is now treated as "no summary".
        """
        summary = (tc.summarized_response or "").strip()
        return "" if summary == "[]" else summary

    @staticmethod
    def _coalesce_consecutive_assistants(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge adjacent assistant messages into one.

        Strict-alternation providers (Qwen, GLM, Kimi, Ollama) reject two
        assistant messages in a row, unlike OpenAI which tolerates it. A message
        carrying ``tool_calls`` is never merged: it is a discrete step that must
        stay paired with the ``tool`` messages answering its call ids.
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            prev = out[-1] if out else None
            mergeable = (
                prev is not None
                and prev.get("role") == "assistant"
                and msg.get("role") == "assistant"
                and not prev.get("tool_calls")
                and not msg.get("tool_calls")
                and isinstance(prev.get("content"), str)
                and isinstance(msg.get("content"), str)
            )
            if not mergeable:
                out.append(msg)
                continue

            joined = "\n\n".join(
                part for part in (prev["content"].strip(), msg["content"].strip()) if part
            )
            out[-1] = {**prev, "content": joined or prev["content"]}
        return out

    def _render_tool_message(self, tc: ToolCallRecord, rcs_enabled: bool, tc_tag_format: str, include_signature: bool) -> str:
        """Render a tool result message according to its RCS status.

        A tool call always yields a tool message: RCS replaces the result body
        with a summary, it never removes the step.

        Rendering rules:
        - Summarized: keep the tool signature (``tool_name(args)``) so the LLM
          knows what was called and with what params, but DROP the ``[TCn]`` tag
          so the result is not eligible for re-summarization in a later turn.
          The summary text replaces the raw response.
        - Not summarized, RCS on: prefix with ``[TCn]`` tag (and signature when
          configured) so the LLM can target it via ``_context_updates``.
        - RCS off: raw response only.

        An empty, whitespace-only, or legacy ``"[]"`` summary counts as *not
        summarized*, so the full raw response is rendered with its tag. That
        keeps sessions written by older versions readable.
        """
        summary = self._summary_text(tc)

        # Summarized — signature kept, [TCn] tag intentionally dropped
        if summary:
            signature = self._format_tool_signature(tc, include_signature)
            if signature:
                return f"{signature}\n{summary}"
            return summary

        # Not summarized
        if rcs_enabled:
            tag = tc_tag_format.format(n=tc.tc_index)
            signature = self._format_tool_signature(tc, include_signature)
            prefix = f"{tag} {signature}\n" if signature else f"{tag}\n"
            return f"{prefix}{tc.raw_response}"

        # RCS disabled: show raw response
        return tc.raw_response

    async def build(
        self,
        session: AgentSession,
        agent_config: AgentConfig,
        current_user_message: Optional[str] = None,
        token_budget: int = 100000,
        user_memory: Optional[dict[str, str]] = None,
        summary_text: str = "",
        run_context: Optional[RunContext] = None,
        skills_catalog: Optional[str] = None,
        explicit_skills_content: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Assemble the complete messages array for the LLM call.

        Applies RCS tagging, inline summaries, memory injection, and token pruning.
        """
        rcs_enabled = agent_config.rcs.enabled
        tc_tag_format = agent_config.rcs.tc_tag_format or "[TC{n}]"
        include_signature = agent_config.rcs.tc_tag_include_tool_signature

        # 1. Build and render System Prompt
        persona_dict = agent_config.persona.model_dump()
        memory_cfg = getattr(agent_config, "memory", None)
        summary_cfg = getattr(agent_config, "context_summary", None)
        facts = user_memory if user_memory is not None else {}
        memory_for_jinja = (
            facts
            if memory_cfg and memory_cfg.enabled and memory_cfg.inject_into_prompt
            else {}
        )
        summary_for_jinja = ""
        if (
            summary_cfg
            and summary_cfg.summarize_on is not None
            and summary_cfg.inject_into_prompt
        ):
            summary_for_jinja = summary_text or ""

        system_content = render_system_prompt(
            persona=persona_dict,
            user_memory=memory_for_jinja,
            summary_text=summary_for_jinja,
            current_date=datetime.now().strftime("%Y-%m-%d"),
            template=agent_config.persona.system_prompt or agent_config.persona.system_prompt_template,
            run_context=run_context,
            session=session,
        )

        system_content = MemoryPromptInjector.inject(
            system_content, facts, memory_cfg
        )
        system_content = SummaryPromptInjector.inject(
            system_content, summary_text or "", summary_cfg
        )

        # Inject RCS System Prompt Block if enabled
        if rcs_enabled:
            system_content = RCSSystemPromptInjector.inject(system_content, agent_config.rcs)

        if explicit_skills_content:
            system_content = f"{system_content}\n\n{explicit_skills_content}"

        if skills_catalog:
            system_content = f"{system_content}\n\n{skills_catalog}"

        system_message = {"role": "system", "content": system_content}

        # 2. Build History Messages
        # We need to map turns into a flat list of user, assistant, and tool messages,
        # applying the RCS rendering rules.
        history_turns: list[list[dict[str, Any]]] = []

        for turn in session.turns:
            turn_messages = []
            
            # Add user message if present
            if turn.user_message:
                turn_messages.append({"role": "user", "content": turn.user_message})

            # Process LLM messages. Every tool call renders a tool message below,
            # so assistant tool_calls are always answered and need no filtering.
            for msg in turn.llm_messages:
                msg_copy = copy.deepcopy(msg)

                if msg_copy.get("role") == "assistant":
                    msg_copy = sanitize_assistant_llm_message(
                        msg_copy, placeholder=EMPTY_ASSISTANT_PLACEHOLDER
                    )

                turn_messages.append(msg_copy)

            # Process Tool results (the 'tool' role messages)
            # We construct these from the ToolCallRecords of the turn
            for tc in turn.tool_calls:
                content = self._render_tool_message(
                    tc=tc,
                    rcs_enabled=rcs_enabled,
                    tc_tag_format=tc_tag_format,
                    include_signature=include_signature,
                )

                # Find the matching tool_call_id from turn's assistant messages
                # To align with LLM tool call requirements
                tool_call_id = f"call_{tc.tc_id}"
                for msg in turn.llm_messages:
                    if msg.get("role") == "assistant" and msg.get("tool_calls"):
                        # Sequence match
                        tc_idx = turn.tool_calls.index(tc)
                        if tc_idx < len(msg["tool_calls"]):
                            tool_call_id = msg["tool_calls"][tc_idx].get("id", tool_call_id)

                turn_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": content,
                })

            history_turns.append(turn_messages)

        # 3. Add current turn user message
        current_messages = []
        if current_user_message:
            current_messages.append({"role": "user", "content": current_user_message})

        # 4. Sliding Window Budgeting
        # We start with the full history and prune oldest turns until it fits inside token_budget.
        # System prompt + current user message are ALWAYS kept.
        
        while history_turns:
            # Flatten history turns
            flat_history = []
            for t_msgs in history_turns:
                flat_history.extend(t_msgs)

            full_messages = [system_message] + flat_history + current_messages
            
            # Count tokens
            model = agent_config.llm.model
            total_tokens = TokenCounter.count_messages(full_messages, model)
            
            if total_tokens <= token_budget:
                break
            
            # Over budget: drop the oldest turn
            logger.info("Context window over budget (%d > %d). Dropping oldest turn.", total_tokens, token_budget)
            history_turns.pop(0)

        # Final flat messages construction
        flat_history = []
        for t_msgs in history_turns:
            flat_history.extend(t_msgs)

        final_messages = self._coalesce_consecutive_assistants(
            [system_message] + flat_history + current_messages
        )

        # Emit observability event (awaited so it is not silently lost)
        if self.event_emitter:
            from nexus.events.models import RCSContextBuiltEvent
            all_tcs = [tc for turn in session.turns for tc in turn.tool_calls]
            tc_summarized_count = sum(1 for tc in all_tcs if self._summary_text(tc))
            tc_tags_count = len(all_tcs) - tc_summarized_count
            await self.event_emitter.emit(
                RCSContextBuiltEvent(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                    context_tokens=TokenCounter.count_messages(final_messages, agent_config.llm.model),
                    turns_in_context=len(history_turns),
                    tc_tags_count=tc_tags_count,
                    tc_summarized_count=tc_summarized_count,
                )
            )

        return final_messages

    def count_rcs_savings(
        self,
        messages: list[dict[str, Any]],
        session: AgentSession,
        agent_config: AgentConfig,
    ) -> int:
        """Compute the recurring input-token savings from RCS for the given context.

        For each tool message in ``messages`` whose TC has been summarized,
        compute what the message WOULD have been without RCS (raw rendering with
        tag + signature + raw_response) and return the total token difference.

        This gives the true recurring savings for the current turn — the input
        tokens saved by having summaries instead of raw results in context. The
        runner accumulates this across turns into
        ``session.cumulative_input_tokens_saved_by_rcs``.
        """
        if not agent_config.rcs.enabled:
            return 0

        model = agent_config.llm.model
        tc_tag_format = agent_config.rcs.tc_tag_format or "[TC{n}]"
        include_signature = agent_config.rcs.tc_tag_include_tool_signature

        # Map call_id → ToolCallRecord for quick lookup
        tc_by_call_id: dict[str, ToolCallRecord] = {}
        for turn in session.turns:
            for tc in turn.tool_calls:
                if tc.call_id:
                    tc_by_call_id[tc.call_id] = tc

        total_savings = 0

        for msg in messages:
            if msg.get("role") != "tool":
                continue
            call_id = msg.get("tool_call_id")
            tc = tc_by_call_id.get(call_id) if call_id else None
            if tc is None:
                continue
            if not self._summary_text(tc):
                continue

            actual_content = msg.get("content") or ""
            actual_tokens = TokenCounter.count_string(actual_content, model)

            tag = tc_tag_format.format(n=tc.tc_index)
            signature = self._format_tool_signature(tc, include_signature)
            counterfactual_prefix = f"{tag} {signature}\n" if signature else f"{tag}\n"
            counterfactual_content = f"{counterfactual_prefix}{tc.raw_response}"
            counterfactual_tokens = TokenCounter.count_string(counterfactual_content, model)

            total_savings += max(0, counterfactual_tokens - actual_tokens)

        return total_savings
