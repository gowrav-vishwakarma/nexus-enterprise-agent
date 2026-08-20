"""Personal agent starter — one operator, durable memory, a terminal chat loop.

Run it:

    export OPENAI_API_KEY=sk-...
    uv run python templates/personal-agent/main.py

Everything is stored under ./agent-data, so state survives restarts. This is the
single-user shape; for many tenants see ../saas-chat/main.py.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from nexus.config.agent import AgentConfig, AgentPersonaConfig, MemoryConfig, TurnConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import MemoryStoreConfig
from nexus.config.storage import SessionStorageConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

DATA_ROOT = Path(os.getenv("AGENT_DATA_ROOT", "./agent-data")).resolve()
NOTES_FILE = DATA_ROOT / "notes.md"


@tool(name="save_note")
def save_note(text: str) -> str:
    """Append a note the agent should remember as a file."""
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with NOTES_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"- {text}\n")
    return f"Saved. {NOTES_FILE.name} now has {len(read_notes().splitlines())} notes."


@tool(name="read_notes")
def read_notes() -> str:
    """Return every note saved so far."""
    if not NOTES_FILE.exists():
        return "No notes yet."
    return NOTES_FILE.read_text(encoding="utf-8")


def build_agent() -> AgentRunner:
    registry = ToolRegistry()
    registry.add_tool(save_note)
    registry.add_tool(read_notes)

    config = AgentConfig(
        name="personal-agent",
        llm=LLMProviderConfig(
            provider="openai",
            model=os.getenv("AGENT_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
        ),
        persona=AgentPersonaConfig(
            role="a concise personal assistant",
            goal="Help with day-to-day tasks and remember what matters",
            backstory="Save anything worth remembering with save_note.",
        ),
        turns=TurnConfig(max_turns=12),
        # Facts learned in one conversation are available in the next.
        memory=MemoryConfig(
            enabled=True,
            namespace="personal",
            stores=[
                MemoryStoreConfig(
                    name="preferences",
                    description="How the operator likes things done",
                )
            ],
        ),
        storage=SessionStorageConfig(
            adapter="sqlite",
            adapter_config={"data_root": str(DATA_ROOT)},
        ),
    )

    # One operator, so the scope is fixed rather than read off a request.
    ctx = RunContext(user_id=os.getenv("AGENT_USER", "me"), persistable=True)
    return AgentRunner(config=config, tool_registry=registry, run_context=ctx)


async def chat_loop() -> None:
    runner = build_agent()
    session_id = os.getenv("AGENT_SESSION", "personal-main")
    print(f"Personal agent ready (session {session_id}). Ctrl-C to quit.\n")

    while True:
        try:
            message = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return
        if not message:
            continue

        print("agent > ", end="", flush=True)
        async for event in runner.run_stream(message, session_id=session_id, stream=True):
            if event.event_type == "content":
                print(event.content or "", end="", flush=True)
            elif event.event_type == "tool_call":
                print(f"\n  [{event.data.get('tool_name')}]", end="", flush=True)
        print("\n")


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY first.")
    asyncio.run(chat_loop())
