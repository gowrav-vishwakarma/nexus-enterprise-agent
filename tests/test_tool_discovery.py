"""Tests for package tool discovery and registry-owned toolsets."""

import sys
from pathlib import Path

import pytest

from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))


@tool(name="sample_tool", description="Sample")
def sample_tool(x: str) -> str:
    return x


@tool(name="other_tool", description="Other")
def other_tool(x: str) -> str:
    return x


def test_add_toolset_registers_tool_objects():
    reg = ToolRegistry()
    reg.add_toolset("pack", [sample_tool, other_tool])
    assert reg.has("sample_tool")
    assert reg.has("other_tool")
    assert reg.resolve_toolset("pack") == {"sample_tool", "other_tool"}


def test_add_tool_flat_name():
    reg = ToolRegistry()
    name = reg.add_tool(sample_tool)
    assert name == "sample_tool"
    assert reg.has("sample_tool")


def test_execute_tool_flat_name():
    import asyncio

    reg = ToolRegistry()
    reg.add_tool(sample_tool)
    out = asyncio.run(reg.execute_tool("sample_tool", {"x": "hi"}, RunContext()))
    assert out == "hi"


def test_discover_package_namespaced():
    reg = ToolRegistry().discover_package(
        "tool_pkg",
        plugin_name="demo",
        skip=set(),
    )
    assert reg.has("demo.discovered_one")
    assert reg.count() == 1


def test_define_toolset_ok_and_resolve():
    reg = ToolRegistry()
    reg.register_tool(sample_tool, plugin_name="app")
    reg.register_tool(other_tool, plugin_name="app")

    reg.define_toolset("leaf", ["app.other_tool"])
    reg.define_toolset("core", ["app.sample_tool"], includes=["leaf"])

    assert reg.has_toolset("core")
    assert reg.resolve_toolset("core") == {"app.sample_tool", "app.other_tool"}
    # A list of names unions their tools; dotted names resolve to themselves.
    assert reg.resolve_toolset(["leaf", "app.sample_tool"]) == {
        "app.other_tool",
        "app.sample_tool",
    }
    assert reg.resolve_toolset(None) is None


def test_define_toolset_missing_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(ValueError, match="app.missing_tool"):
        reg.define_toolset("core", ["app.missing_tool"])


def test_define_toolset_missing_include_raises():
    reg = ToolRegistry()
    reg.register_tool(sample_tool, plugin_name="app")
    with pytest.raises(ValueError, match="undefined_child"):
        reg.define_toolset(
            "core", ["app.sample_tool"], includes=["undefined_child"]
        )


def _make_runner(reg: ToolRegistry, toolset):
    from nexus.config.agent import AgentConfig, AgentPersonaConfig
    from nexus.config.llm import LLMProviderConfig
    from nexus.runner.agent_runner import AgentRunner

    config = AgentConfig(
        name="grant_agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini"),
        persona=AgentPersonaConfig(role="Helper", goal="Help"),
        toolset=toolset,
    )
    return AgentRunner(config=config, tool_registry=reg)


def test_runtime_grant_widens_allow_list():
    reg = ToolRegistry()
    reg.register_tool(sample_tool, plugin_name="app")
    reg.register_tool(other_tool, plugin_name="app")
    reg.define_toolset("core", ["app.sample_tool"])
    reg.define_toolset("extra", ["app.other_tool"])

    runner = _make_runner(reg, toolset="core")
    runner._resolve_toolsets()
    assert runner._allowed_tools == {"app.sample_tool"}

    runner.grant_tools("app.other_tool")
    assert runner._allowed_tools == {"app.sample_tool", "app.other_tool"}

    runner.revoke_tools("app.other_tool")
    assert runner._allowed_tools == {"app.sample_tool"}

    runner.grant_toolset("extra")
    assert runner._allowed_tools == {"app.sample_tool", "app.other_tool"}


def test_runtime_grant_noop_when_unrestricted():
    reg = ToolRegistry()
    reg.register_tool(sample_tool, plugin_name="app")

    runner = _make_runner(reg, toolset=None)
    runner._resolve_toolsets()
    # No toolset restriction: every registered tool is already visible.
    assert runner._allowed_tools is None
    runner.grant_tools("app.sample_tool")
    assert runner._allowed_tools is None
