#!/usr/bin/env python3
"""Run a YAML-defined multi-agent team."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from nexus import OrchestrationManifest, OrchestrationRuntime, RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(name="web_search", description="Search the web for a query.")
def web_search(query: str) -> str:
    return f"Web search result for: '{query}' - found research releases."


@tool(name="database_query", description="Query the company database.")
def database_query(sql: str) -> str:
    return f"Database result: queried '{sql}' (returned 0 rows)."


EXAMPLE_DIR = Path(__file__).resolve().parent


def build_example_registry() -> ToolRegistry:
    """Build a registry with the research-team toolsets."""
    registry = ToolRegistry()
    registry.add_toolset("researcher", [web_search])
    registry.add_toolset("analyst", [database_query])
    return registry


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a YAML orchestration manifest")
    parser.add_argument(
        "--manifest",
        default=str(EXAMPLE_DIR / "research_team.yaml"),
        help="Path to orchestration YAML manifest",
    )
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument(
        "--user-id",
        default="demo-user",
        help="Scopes chat history and cross-session user_memory (tenant + user)",
    )
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
        tool_registry=build_example_registry(),
    )

    result = await runtime.run(args.message)
    print(result.final_response)
    print(f"session_id={session_id}")


if __name__ == "__main__":
    asyncio.run(main())
