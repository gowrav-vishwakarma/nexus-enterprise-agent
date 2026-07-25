#!/usr/bin/env python3
"""Run a Python-defined multi-agent team (supervisor + nested pipeline)."""

from __future__ import annotations

import argparse
import asyncio
import os
from uuid import uuid4

from pydantic import SecretStr

from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(name="web_search", description="Search the web for a query.")
def web_search(query: str) -> str:
    return f"Web search result for: '{query}' - found research releases."


@tool(name="database_query", description="Query the company database.")
def database_query(sql: str) -> str:
    return f"Database result: queried '{sql}' (returned 0 rows)."


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add_toolset("researcher", [web_search])
    registry.add_toolset("analyst", [database_query])
    return registry


def build_llm() -> LLMProviderConfig:
    return LLMProviderConfig(
        provider="openai",
        model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
        api_key=SecretStr(os.environ.get("OPENAI_API_KEY", "mock-key")),
    )


def build_research_team() -> AgentGroupConfig:
    llm = build_llm()

    supervisor_cfg = AgentConfig(
        name="supervisor",
        llm=llm,
        persona=AgentPersonaConfig(
            role="Supervisor",
            goal="Coordinate the research team",
        ),
    )
    researcher_cfg = AgentConfig(
        name="researcher",
        llm=llm,
        toolset="researcher",
        persona=AgentPersonaConfig(
            role="Researcher",
            goal="Gather facts from the web",
        ),
    )
    analyst_cfg = AgentConfig(
        name="analyst",
        llm=llm,
        toolset="analyst",
        persona=AgentPersonaConfig(
            role="Analyst",
            goal="Analyze structured data",
        ),
    )

    analysis_pipeline = AgentGroupConfig(
        name="analysis_pipeline",
        pattern="pipeline",
        session_id_prefix="pipe_",
        members=[researcher_cfg, analyst_cfg],
    )
    return AgentGroupConfig(
        name="research_team",
        pattern="supervisor",
        session_id_prefix="team_",
        supervisor="supervisor",
        members=[supervisor_cfg, analysis_pipeline],
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Python-defined research team")
    parser.add_argument("--tenant-id", default="demo-tenant")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "message",
        nargs="?",
        default="Summarize recent framework releases.",
    )
    args = parser.parse_args()

    session_id = args.session_id or str(uuid4())
    orchestrator = AgentOrchestrator(
        config=build_research_team(),
        tool_registry=build_registry(),
        run_context=RunContext(
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            session_id=session_id,
        ),
    )

    result = await orchestrator.run(args.message)
    print(result.final_response)
    print(f"session_id={session_id}")


if __name__ == "__main__":
    asyncio.run(main())
