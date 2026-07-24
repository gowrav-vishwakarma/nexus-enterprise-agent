"""Run the half-duplex IVR voice agent over a local simulation.

This demonstrates the cascaded voice pipeline (VAD -> STT -> AgentRunner -> TTS)
driven by the ``ivr_support`` manifest. It uses the in-memory transport and the
"mock" STT/TTS providers by default, so it runs without any provider keys or
audio hardware -- "audio" is just bytes you feed in.

For a real phone deployment, replace the InMemoryTransport with a
WebSocketTransport (server frames) or a SIP bridge, and set real STT/TTS
providers in the manifest (or via env vars).

Usage:
    uv run python examples/realtime_ivr_server.py "I want to pay my bill"
"""

import asyncio
import sys
from pathlib import Path

from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.runtime import RealtimeRuntime
from nexus.realtime.session import RealtimeSession
from nexus.realtime.tools.ivr import IVRMenuPlugin
from nexus.realtime.transport.memory import InMemoryTransport
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

MANIFEST = Path(__file__).parent / "orchestration" / "ivr_support.yaml"


def build_ivr_registry() -> ToolRegistry:
    """Build a registry with the IVR plugin tools exposed as a toolset."""
    registry = ToolRegistry()
    registry.register_plugin(IVRMenuPlugin())
    ivr_tools = [name for name in registry.tool_names() if name.startswith("ivr_menu.")]
    registry.add_toolset("ivr_menu", ivr_tools)
    return registry


async def main(caller_says: str) -> None:
    manifest = OrchestrationManifest.load(MANIFEST)
    run_context = RunContext(
        tenant_id="demo",
        user_id="+15551234567",
        session_id="call-001",
    )
    runtime = RealtimeRuntime.from_manifest(
        manifest,
        run_context=run_context,
        tool_registry=build_ivr_registry(),
    )
    pipeline = runtime.build_pipeline("ivr_support")

    transport = InMemoryTransport()
    session = RealtimeSession(pipeline, transport, session_id=run_context.session_id)

    # Drive one turn of text directly (skipping STT) for a clear demo.
    print(f"Caller: {caller_says}\n")
    await session.run_text(caller_says)

    for event in transport.sent_events:
        if event.event_type == "content" and event.content:
            print(f"Agent (text): {event.content}", end="")
        elif event.event_type == "audio_out":
            print(f"\n[audio chunk: {len(event.audio or b'')} bytes]")
        elif event.event_type == "tool_call":
            print(f"\n[tool_call: {event.data}]")
        elif event.event_type == "final_response":
            actions = (event.data or {}).get("ivr_actions")
            print(f"\n\nFinal: {event.content}")
            if actions:
                print(f"IVR actions: {actions}")


if __name__ == "__main__":
    message = sys.argv[1] if len(sys.argv) > 1 else "I need to pay my bill"
    asyncio.run(main(message))
