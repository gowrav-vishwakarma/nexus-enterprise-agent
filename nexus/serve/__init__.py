"""Mountable FastAPI routers for Nexus agent apps."""

from nexus.serve.router import create_agent_router, AgentRouterConfig

__all__ = ["create_agent_router", "AgentRouterConfig"]
