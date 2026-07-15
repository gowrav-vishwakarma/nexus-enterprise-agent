"""Flat (unprefixed) tool registration and tricky signatures."""

from typing import Optional

import pytest

from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(name="execute_sql", description="Run SQL")
def execute_sql(sql: str) -> str:
    return "ok"


@tool(
    name="ask_clarification",
    description="Ask the user a clarifying question",
    execution="client",
)
def ask_clarification(
    question: str,
    options: list[dict[str, str]],
    ctx: Optional[RunContext] = None,
    **kwargs,
) -> str:
    """Mirrors aitalk-nexus builtin: Optional[RunContext] + **kwargs."""
    return f"q={question};n={len(options)};sid={ctx.session_id if ctx else None}"


def test_flat_register_tool():
    reg = ToolRegistry()
    reg.register_tool(execute_sql, plugin_name="")
    assert "execute_sql" in reg._tools
    schemas = reg.get_tool_schemas_for_llm()
    names = {s["name"] for s in schemas}
    assert "execute_sql" in names
    assert reg._tool_metadata["execute_sql"]["plugin"] == ""


def test_flat_tool_survives_plugin_filter():
    """Flat tools have plugin=\"\"; plugin allow-lists must not drop them."""
    reg = ToolRegistry()
    reg.register_tool(execute_sql, plugin_name="")
    schemas = reg.get_tool_schemas_for_llm(plugin_names=["other_plugin"])
    names = {s["name"] for s in schemas}
    assert "execute_sql" in names


def test_optional_run_context_and_kwargs_excluded_from_schema():
    """Optional[RunContext] and **kwargs must not appear in LLM parameters."""
    reg = ToolRegistry()
    reg.register_tool(ask_clarification, plugin_name="")
    schemas = reg.get_tool_schemas_for_llm()
    assert len(schemas) == 1
    props = schemas[0]["parameters"]["properties"]
    assert set(props) == {"question", "options"}
    assert "ctx" not in props
    assert "kwargs" not in props
    assert schemas[0]["name"] == "ask_clarification"
    assert reg.get_execution_mode("ask_clarification") == "client"


@pytest.mark.asyncio
async def test_optional_run_context_injected_on_execute():
    reg = ToolRegistry()
    reg.register_tool(ask_clarification, plugin_name="")
    ctx = RunContext(session_id="sess-1")
    result = await reg.execute(
        plugin="ask_clarification",
        tool="",
        args={
            "question": "Which report?",
            "options": [{"label": "A", "value": "a"}, {"label": "B", "value": "b"}],
        },
        run_context=ctx,
    )
    assert result == "q=Which report?;n=2;sid=sess-1"



@tool(name="tool_pep604_run_context", description="PEP 604 RunContext union")
def tool_pep604_run_context(
    label: str,
    run_context: RunContext | None = None,
) -> str:
    return f"{label}:{run_context.session_id if run_context else None}"


@tool(name="tool_bare_run_context_name", description="run_context by name only")
def tool_bare_run_context_name(label: str, run_context=None) -> str:
    return f"{label}:{run_context.session_id if run_context else None}"


def test_pep604_run_context_excluded_from_schema():
    reg = ToolRegistry()
    reg.register_tool(tool_pep604_run_context, plugin_name="")
    props = reg.get_tool_schemas_for_llm()[0]["parameters"]["properties"]
    assert set(props) == {"label"}
    assert "run_context" not in props


@pytest.mark.asyncio
async def test_pep604_run_context_injected_on_execute():
    reg = ToolRegistry()
    reg.register_tool(tool_pep604_run_context, plugin_name="")
    ctx = RunContext(session_id="pep604-sess")
    result = await reg.execute(
        plugin="tool_pep604_run_context",
        tool="",
        args={"label": "x"},
        run_context=ctx,
    )
    assert result == "x:pep604-sess"


def test_bare_run_context_name_excluded_from_schema():
    reg = ToolRegistry()
    reg.register_tool(tool_bare_run_context_name, plugin_name="")
    props = reg.get_tool_schemas_for_llm()[0]["parameters"]["properties"]
    assert set(props) == {"label"}
    assert "run_context" not in props


@pytest.mark.asyncio
async def test_bare_run_context_name_injected_on_execute():
    reg = ToolRegistry()
    reg.register_tool(tool_bare_run_context_name, plugin_name="")
    ctx = RunContext(session_id="bare-sess")
    result = await reg.execute(
        plugin="tool_bare_run_context_name",
        tool="",
        args={"label": "y"},
        run_context=ctx,
    )
    assert result == "y:bare-sess"
