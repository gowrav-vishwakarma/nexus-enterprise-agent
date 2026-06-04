"""Tests for ToolRegistry, decorators, and schemas."""

import pytest

from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin
from nexus.tools.registry import ToolRegistry


# 1. Define sample tools & plugins
@tool(name="add_numbers", description="Adds two numbers.")
def add_numbers_tool(a: int, b: int) -> int:
    return a + b


@tool(name="get_session_info")
def get_session_info_tool(context: RunContext) -> str:
    """Returns the current session ID."""
    return context.session_id or "no-session"


@tool_plugin(name="math_plugin")
class MathPlugin:
    
    @tool()
    def multiply(self, x: float, y: float) -> float:
        """Multiply two floats."""
        return x * y

    @tool(requires_approval=True)
    async def divide(self, x: float, y: float) -> float:
        """Divide two floats asynchronously."""
        if y == 0:
            raise ZeroDivisionError("division by zero")
        return x / y


@pytest.mark.asyncio
async def test_standalone_tool_registration():
    """Test standalone tool decorators and registration."""
    registry = ToolRegistry()
    registry.register_tool(add_numbers_tool)

    # Verify metadata
    metadata = registry._tool_metadata["global.add_numbers"]
    assert metadata["name"] == "add_numbers"
    assert metadata["description"] == "Adds two numbers."
    assert metadata["requires_approval"] is False

    # Execute
    res = await registry.execute(
        plugin="global",
        tool="add_numbers",
        args={"a": 5, "b": 10},
        run_context=RunContext(),
    )
    assert res == 15


@pytest.mark.asyncio
async def test_plugin_registration():
    """Test namespace and method registration from a tool class plugin."""
    registry = ToolRegistry()
    plugin = MathPlugin()
    registry.register_plugin(plugin)

    # Verify namespace prefix
    assert "math_plugin.multiply" in registry._tools
    assert "math_plugin.divide" in registry._tools

    # Execute sync method
    res_mult = await registry.execute(
        plugin="math_plugin",
        tool="multiply",
        args={"x": 3.0, "y": 4.0},
        run_context=RunContext(),
    )
    assert res_mult == 12.0

    # Execute async method
    res_div = await registry.execute(
        plugin="math_plugin",
        tool="divide",
        args={"x": 10.0, "y": 2.0},
        run_context=RunContext(),
    )
    assert res_div == 5.0


@pytest.mark.asyncio
async def test_run_context_injection():
    """Test that RunContext parameter is skipped in schema but injected at call time."""
    registry = ToolRegistry()
    registry.register_tool(get_session_info_tool)

    # Verify RunContext is NOT in parameters schema
    schemas = registry.get_tool_schemas_for_llm()
    schema = schemas[0]
    assert "context" not in schema["parameters"]["properties"]

    # Execute and check context was injected
    ctx = RunContext(session_id="test_session_xyz")
    res = await registry.execute(
        plugin="global",
        tool="get_session_info",
        args={},
        run_context=ctx,
    )
    assert res == "test_session_xyz"


def test_rcs_schema_injection():
    """Test that _context_updates is injected when RCS is enabled."""
    registry = ToolRegistry()
    registry.register_tool(add_numbers_tool)

    # RCS Disabled
    rcs_config_disabled = RuntimeContextSummarizerConfig(enabled=False)
    schemas_disabled = registry.get_tool_schemas_for_llm(rcs_config=rcs_config_disabled)
    assert "_context_updates" not in schemas_disabled[0]["parameters"]["properties"]

    # RCS Enabled
    rcs_config_enabled = RuntimeContextSummarizerConfig(
        enabled=True,
        context_updates_param_name="_my_updates",
    )
    schemas_enabled = registry.get_tool_schemas_for_llm(rcs_config=rcs_config_enabled)
    properties = schemas_enabled[0]["parameters"]["properties"]
    assert "_my_updates" in properties
    assert properties["_my_updates"]["type"] == "array"
