"""Test tool plugin for orchestration manifest loading."""

from nexus.tools.decorators import tool, tool_plugin


@tool_plugin(name="fixture_search")
class FixtureSearchPlugin:
    @tool(name="search")
    def search(self, query: str) -> str:
        """Search fixture index."""
        return f"fixture result for {query}"
