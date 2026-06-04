"""Context window builder for the Nexus Agent Framework."""

import copy
import logging
from datetime import datetime
from typing import Any, Optional

from nexus.config.agent import AgentConfig
from nexus.context.rcs_injector import RCSSystemPromptInjector
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord
from nexus.utils.jinja import render_system_prompt
from nexus.llm.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class ContextWindowBuilder:
    """Builds and manages the message sequence for the LLM context window."""

    def __init__(self, event_emitter: Optional[Any] = None):
        self.event_emitter = event_emitter

    def _render_tool_message(self, tc: ToolCallRecord, rcs_enabled: bool, tc_tag_format: str, include_signature: bool) -> Optional[str]:
        """Render a tool result message according to its RCS status.

        Returns None if the tool call is dropped.
        """
        # Case 3: Dropped
        if tc.is_dropped or tc.summarized_response == "[]":
            return None

        # Case 2: Summarized
        if tc.summarized_response is not None:
            return f"{tc.tool_name} result: {tc.summarized_response}"

        # Case 1: Unsummarized
        if rcs_enabled:
            # Build TC tag e.g. [TC1]
            tag = tc_tag_format.format(n=tc.tc_index)
            if include_signature:
                # Format: [TC1] tool_name(args...)
                import json
                args_str = ", ".join(f"{k}={json.dumps(v)}" for k, v in tc.tool_input.items() if k != "_context_updates")
                prefix = f"{tag} {tc.tool_name}({args_str})\n"
            else:
                prefix = f"{tag}\n"
            return f"{prefix}{tc.raw_response}"
        
        # RCS disabled: show raw response
        return tc.raw_response

    def build(
        self,
        session: AgentSession,
        agent_config: AgentConfig,
        current_user_message: Optional[str] = None,
        token_budget: int = 100000,
        cross_session_entity_memory: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        """Assemble the complete messages array for the LLM call.

        Applies RCS tagging, inline summaries, memory injection, and token pruning.
        """
        rcs_enabled = agent_config.rcs.enabled
        tc_tag_format = agent_config.rcs.tc_tag_format or "[TC{n}]"
        include_signature = agent_config.rcs.tc_tag_include_tool_signature

        # 1. Build and render System Prompt
        persona_dict = agent_config.persona.model_dump()
        inject_memory = getattr(agent_config.session_memory, "inject_into_prompt", True)
        cross_cfg = getattr(agent_config.session_memory, "cross_session", None)
        inject_cross_session = bool(
            cross_cfg
            and cross_cfg.enabled
            and cross_session_entity_memory
        )
        system_content = render_system_prompt(
            persona=persona_dict,
            working_memory=session.working_memory if inject_memory else "",
            entity_memory=session.entity_memory if inject_memory else {},
            cross_session_entity_memory=cross_session_entity_memory if inject_cross_session else {},
            current_date=datetime.now().strftime("%Y-%m-%d"),
            template=agent_config.persona.system_prompt or agent_config.persona.system_prompt_template,
        )

        # Inject RCS System Prompt Block if enabled
        if rcs_enabled:
            system_content = RCSSystemPromptInjector.inject(system_content, agent_config.rcs)

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

            # We need to match LLM messages (assistant) and Tool Call messages (tool)
            # and render/prune them based on dropped/summarized TCs.
            dropped_tc_ids = set()
            for tc in turn.tool_calls:
                if tc.is_dropped or tc.summarized_response == "[]":
                    dropped_tc_ids.add(tc.tc_id)

            # Process LLM messages
            for msg in turn.llm_messages:
                msg_copy = copy.deepcopy(msg)
                
                # If there are tool calls inside assistant message, we strip the ones that are dropped
                if msg_copy.get("role") == "assistant" and msg_copy.get("tool_calls"):
                    filtered_calls = []
                    for tc_call in msg_copy["tool_calls"]:
                        tc_id = tc_call.get("id")
                        # Match by id or index if needed
                        # In turn records, tool_calls has ToolCallRecord.
                        # Let's see: we can match by comparing tool name / input if ID isn't a direct match
                        # But typically the ID is the tool call ID returned by LLM.
                        
                        # Find corresponding ToolCallRecord
                        matching_tc = None
                        for record in turn.tool_calls:
                            # We can check record.tc_index or we can store the raw LLM tool call ID
                            # Let's see: if we matched the TC index, we can identify it.
                            # Usually, TurnRecord.tool_calls is populated sequentially.
                            pass

                        # If this tool call was dropped, we filter it out of the assistant message to keep provider APIs happy
                        # We also filter out corresponding 'tool' message.
                        # To map raw LLM tool_call IDs to our internal TC1, TC2, etc:
                        # Let's map sequentially for this turn.
                        tc_index_in_turn = msg_copy["tool_calls"].index(tc_call)
                        if tc_index_in_turn < len(turn.tool_calls):
                            record = turn.tool_calls[tc_index_in_turn]
                            if record.tc_id in dropped_tc_ids:
                                continue
                        
                        filtered_calls.append(tc_call)
                    
                    msg_copy["tool_calls"] = filtered_calls
                    # If assistant message has empty tool_calls and no content, we can still yield a dummy content or omit it
                    if not msg_copy["tool_calls"] and not msg_copy.get("content"):
                        msg_copy["content"] = "Executed background processing."

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
                if content is None:
                    # Dropped
                    continue

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

        final_messages = [system_message] + flat_history + current_messages

        # Emit observability event
        if self.event_emitter:
            from nexus.events.models import RCSContextBuiltEvent
            tc_tags_count = sum(1 for turn in session.turns for tc in turn.tool_calls if tc.summarized_response is None)
            tc_summarized_count = sum(1 for turn in session.turns for tc in turn.tool_calls if tc.summarized_response is not None)
            
            # Import loop-safe inside build
            import asyncio
            asyncio.create_task(
                self.event_emitter.emit(
                    RCSContextBuiltEvent(
                        session_id=session.session_id,
                        agent_id=session.agent_id,
                        context_tokens=TokenCounter.count_messages(final_messages, agent_config.llm.model),
                        turns_in_context=len(history_turns),
                        tc_tags_count=tc_tags_count,
                        tc_summarized_count=tc_summarized_count,
                    )
                )
            )

        return final_messages
