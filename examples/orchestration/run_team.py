#!/usr/bin/env python3
"""Run a YAML-defined multi-agent team."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from nexus import OrchestrationManifest, OrchestrationRuntime, RunContext

EXAMPLE_DIR = Path(__file__).resolve().parent


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a YAML orchestration manifest")
    parser.add_argument(
        "manifest",
        nargs="?",
        default=str(EXAMPLE_DIR / "research_team.yaml"),
        help="Path to orchestration YAML manifest",
    )
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("message", nargs="?", default="Summarize recent framework releases.")
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

    result = await runtime.run(args.message)
    print(result.final_response)
    print(f"session_id={session_id}")


if __name__ == "__main__":
    asyncio.run(main())
