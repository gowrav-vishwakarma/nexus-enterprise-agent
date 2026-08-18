#!/usr/bin/env python3
"""Load the RAG + memory YAML example, ingest a few docs, and run one turn.

Usage:

    uv run python examples/orchestration/run_rag_memory.py "What is photosynthesis?"
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from nexus import OrchestrationManifest, OrchestrationRuntime, RunContext
from nexus.runner.agent_runner import AgentRunner

EXAMPLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXAMPLE_DIR.parent


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RAG + memory orchestration example")
    parser.add_argument(
        "--manifest",
        default=str(REPO_ROOT / "rag_memory_manifest.yaml"),
        help="Path to the RAG/memory YAML manifest",
    )
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "message",
        nargs="?",
        default="What is photosynthesis?",
    )
    args = parser.parse_args()

    manifest = OrchestrationManifest.load(args.manifest)
    session_id = args.session_id or str(uuid4())
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            session_id=session_id,
        ),
    )

    executor = runtime.executor
    if isinstance(executor, AgentRunner) and executor.rag_provider is not None:
        await executor.rag_provider.ingest(
            runtime.run_context,
            [
                "Photosynthesis converts sunlight into chemical energy in plants.",
                "Paris is the capital of France.",
                "The Nile is a long river in Africa.",
            ],
        )

    result = await runtime.run(args.message)
    print(result.final_response)
    print(f"session_id={session_id}")


if __name__ == "__main__":
    asyncio.run(main())
