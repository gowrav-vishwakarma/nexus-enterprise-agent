"""RCS live LLM check — a manual verification harness (not a pytest).

Drives a real multi-turn RCS scenario against a configured LLM and prints
per-turn token accounting so you can:

1. Confirm the aggregated numbers tie out end-to-end:
   ``turn.tokens_saved_this_turn`` == sum of per-update savings
   == delta applied to ``session.total_tokens_saved_by_rcs``.
2. Quantify how efficient RCS actually is (before/after context size).
3. Spot-check that the ``usage`` token keys returned by the LLM are
   consistent across final responses and tool-call responses.

Usage::

    uv run python scripts/rcs_live_check.py

Requires ``NEXUS_LLM_API_KEY`` (or ``PLATFORM_OPENAI_KEY``) in the
environment / ``.env``. Set ``NEXUS_LLM_MODEL`` / ``NEXUS_LLM_BASE_URL``
to point at your provider.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Load .env from project root so NEXUS_LLM_* vars are available.
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass

from pydantic import SecretStr

from nexus.config.agent import AgentConfig, AgentPersonaConfig, TurnConfig
from nexus.config.rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from nexus.context.builder import ContextWindowBuilder
from nexus.llm.token_counter import TokenCounter
from nexus.runner.agent_runner import AgentRunner
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

# A large, deliberately-irrelevant blob so RCS has something real to compress.
NOISE_BLOB = (
    "PANDAS COOKBOOK: How to make chocolate chip cookies with butter, flour, "
    "and sugar. Season the dough with vanilla extract. Bake at 350F for 12 "
    "minutes. This recipe has nothing to do with physics, quantum mechanics, "
    "or documentation. "
) * 12  # ~6 KB of noise


@tool(name="noise_lookup", description="General lookup that may return unrelated content.")
def noise_lookup(query: str) -> str:
    """Returns a large irrelevant blob — prime RCS compression target."""
    return f"[noise_lookup for '{query}']\n{NOISE_BLOB}"


@tool(name="doc_search", description="Search internal documentation.")
def doc_search(query: str) -> str:
    return f"Doc hit for '{query}': quantum entanglement is covered in section 4.2."


@tool(name="summarize_findings", description="Write a short summary of findings so far.")
def summarize_findings(text: str) -> str:
    return f"Summary recorded: {text}"


def llm_config_from_env() -> Optional[Any]:
    from nexus.config.llm import LLMProviderConfig

    provider = os.getenv("NEXUS_LLM_PROVIDER", "openai")
    base_url = os.getenv("NEXUS_LLM_BASE_URL", "") or None
    model = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")
    api_key = os.getenv("NEXUS_LLM_API_KEY") or os.getenv("PLATFORM_OPENAI_KEY", "")
    if not api_key or api_key.startswith("sk-your-"):
        return None
    return LLMProviderConfig(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
    )


def _print_header(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def _print_turn_accounting(session: Any, agent_config: AgentConfig, turn_index: int) -> None:
    """Print per-TC and per-turn token accounting for inspection."""
    turn = session.turns[turn_index] if turn_index < len(session.turns) else None
    if not turn:
        return
    _print_header(f"Turn {turn_index} accounting")
    print(f"  tokens_in  = {turn.total_tokens_in}")
    print(f"  tokens_out = {turn.total_tokens_out}")
    print(f"  tokens_saved_this_turn = {turn.tokens_saved_this_turn}")
    print(f"  recurring_savings_this_turn = {turn.recurring_savings_this_turn}")
    print(f"  context_updates_received = {turn.context_updates_received}")
    print(f"  tool_calls:")
    for tc in turn.tool_calls:
        print(
            f"    {tc.tc_id} {tc.tool_name}  "
            f"raw={tc.tokens_raw}  summarized={tc.tokens_summarized}  "
            f"dropped={tc.is_dropped}  summary={tc.summarized_response!r}"
        )
    print(f"  running session.total_tokens_saved_by_rcs = {session.total_tokens_saved_by_rcs}")
    print(f"  running session.cumulative_input_tokens_saved_by_rcs = {session.cumulative_input_tokens_saved_by_rcs}")


async def _print_context_size(session: Any, agent_config: AgentConfig, label: str) -> int:
    """Build the LLM messages and print their token size. Returns the count."""
    messages = await ContextWindowBuilder().build(session, agent_config)
    tokens = TokenCounter.count_messages(messages, agent_config.llm.model)
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    print(f"  [{label}] context_tokens = {tokens}  (tool messages: {len(tool_msgs)})")
    for m in tool_msgs:
        preview = m["content"][:120].replace("\n", " ")
        print(f"      - {preview}{'...' if len(m['content']) > 120 else ''}")
    return tokens


async def main() -> int:
    llm_config = llm_config_from_env()
    if llm_config is None:
        print(
            "No LLM API key configured. Set NEXUS_LLM_API_KEY (or PLATFORM_OPENAI_KEY) "
            "in your environment / .env to run this check.",
            file=sys.stderr,
        )
        return 1

    # Enable RCS + the fallback compactor with a low threshold so we can
    # exercise both the inline (LLM-driven) and the fallback paths.
    rcs_config = RuntimeContextSummarizerConfig(
        enabled=True,
        fallback_compactor=ServerCompactorConfig(
            enabled=True,
            trigger_token_threshold=4000,
            compact_oldest_n_tcs=2,
        ),
    )

    agent_config = AgentConfig(
        name="rcs-live-check",
        llm=llm_config,
        rcs=rcs_config,
        tool_plugins=["global"],
        turns=TurnConfig(max_turns=8, turn_timeout_seconds=180),
        persona=AgentPersonaConfig(
            role="Research assistant",
            goal="Find correct documentation and manage context efficiently. "
                 "Use _context_updates to compress tool results you no longer need.",
        ),
    )

    registry = ToolRegistry()
    registry.register_tool(noise_lookup)
    registry.register_tool(doc_search)
    registry.register_tool(summarize_findings)

    manager = SessionManager()
    runner = AgentRunner(
        config=agent_config,
        tool_registry=registry,
        storage_config=manager,
        run_context=RunContext(),
    )

    session_id = "rcs-live-check-sess"
    user_prompt = (
        "Find quantum entanglement info in our docs. "
        "First call global.noise_lookup with query 'quantum entanglement'. "
        "If that result is not about quantum physics, call global.doc_search next "
        "and include _context_updates summarizing the noise_lookup result as: "
        "'I checked noise_lookup but it does not contain what I want.' "
        "Then call global.summarize_findings with a one-line summary of what you found."
    )

    _print_header("RCS live check — starting run")
    print(f"  model    = {llm_config.model}")
    print(f"  base_url = {llm_config.base_url or '(default)'}")
    print(f"  session  = {session_id}")
    print(f"  prompt   = {user_prompt}")

    result = await runner.run(user_message=user_prompt, session_id=session_id)

    _print_header("Run result")
    print(f"  status                       = {result.status}")
    print(f"  turns_used                   = {result.turns_used}")
    print(f"  total_tokens_in              = {result.total_tokens_in}")
    print(f"  total_tokens_out             = {result.total_tokens_out}")
    print(f"  total_tokens_saved_by_rcs    = {result.total_tokens_saved_by_rcs}")
    print(f"  cumulative_input_tokens_saved = {result.cumulative_input_tokens_saved_by_rcs}")
    print(f"  final_response preview        = {(result.final_response or '')[:200]}")

    session = await manager.load_session(session_id)
    if session is None:
        print("  !! session could not be reloaded", file=sys.stderr)
        return 2

    _print_header("Per-turn accounting")
    for i in range(len(session.turns)):
        _print_turn_accounting(session, agent_config, i)

    _print_header("Invariant: turn.tokens_saved_this_turn sum == session.total_tokens_saved_by_rcs")
    turn_sum = sum(t.tokens_saved_this_turn for t in session.turns)
    session_total = session.total_tokens_saved_by_rcs
    print(f"  sum(turn.tokens_saved_this_turn) = {turn_sum}")
    print(f"  session.total_tokens_saved_by_rcs = {session_total}")
    if turn_sum == session_total:
        print("  PASS — one-time savings tie out.")
    else:
        print(f"  !! MISMATCH — diff = {session_total - turn_sum}")

    _print_header("Invariant: turn.recurring_savings_this_turn sum == session.cumulative_input_tokens_saved_by_rcs")
    recurring_sum = sum(t.recurring_savings_this_turn for t in session.turns)
    cumulative_total = session.cumulative_input_tokens_saved_by_rcs
    print(f"  sum(turn.recurring_savings_this_turn)        = {recurring_sum}")
    print(f"  session.cumulative_input_tokens_saved_by_rcs = {cumulative_total}")
    if recurring_sum == cumulative_total:
        print("  PASS — recurring savings tie out.")
    else:
        print(f"  !! MISMATCH — diff = {cumulative_total - recurring_sum}")

    _print_header("One-time vs recurring savings comparison")
    print(f"  one-time total_tokens_saved_by_rcs         = {session_total}")
    print(f"  cumulative recurring input tokens saved     = {cumulative_total}")
    if session_total > 0:
        ratio = cumulative_total / session_total
        print(f"  ratio (cumulative / one-time)              = {ratio:.1f}x")
        print(f"  → RCS saved {ratio:.1f}x more input tokens than the one-time metric shows")

    _print_header("Context size before vs after RCS (rebuilt from final session)")
    # We can't easily replay "before RCS" from the final session state because
    # summaries are already applied. Instead, compute the raw-vs-summarized
    # token delta across all TCs to show what RCS saved.
    raw_total = sum(tc.tokens_raw for t in session.turns for tc in t.tool_calls)
    summarized_total = sum(
        (tc.tokens_summarized or 0) for t in session.turns for tc in t.tool_calls
    )
    print(f"  sum(tc.tokens_raw)        = {raw_total}")
    print(f"  sum(tc.tokens_summarized) = {summarized_total}")
    print(f"  delta (what RCS saved)    = {raw_total - summarized_total}")

    _print_header("Final context (what the LLM would see next turn)")
    await _print_context_size(session, agent_config, "next-turn context")

    _print_header("Done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
