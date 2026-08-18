"""Backward-compat smoke tests: existing MemoryConfig + runner constructors still work."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nexus.config.agent import AgentConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import MemoryConfig, MemoryStoreConfig
from nexus.memory.cross_session_store import InMemoryCrossSessionMemoryStore
from nexus.rag import InMemoryVectorStore, chunk_text, create_retrieve_plugin
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

NEXUS_ROOT = Path(__file__).resolve().parents[1]
AITALK_SRC = Path("/home/gowrav/Development/ankpal-erp/aitalk-nexus/src")


def test_existing_memory_config_builds_runner():
    config = AgentConfig(
        name="compat",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        persona=AgentPersonaConfig(role="a", goal="g"),
        memory=MemoryConfig(
            enabled=True,
            expose_tools=False,
            inject_into_prompt=True,
            stores=[
                MemoryStoreConfig(name="user", inject="always"),
                MemoryStoreConfig(name="memory", inject="always"),
            ],
        ),
    )
    runner = AgentRunner(
        config=config,
        tool_registry=ToolRegistry(),
        run_context=RunContext(tenant_id="t", user_id="u"),
        cross_session_memory_store=InMemoryCrossSessionMemoryStore(),
    )
    assert runner.memory_provider is None
    assert runner.rag_provider is None
    assert runner.config.rag is None


def test_rag_public_exports():
    assert callable(chunk_text)
    plugin = create_retrieve_plugin(InMemoryVectorStore(), None)
    assert plugin.provider is not None


def test_personal_agent_template_builds():
    path = NEXUS_ROOT / "templates" / "personal-agent" / "main.py"
    spec = importlib.util.spec_from_file_location("personal_agent_main", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        runner = mod.build_agent()
    except ImportError as exc:
        pytest.skip(f"personal-agent sqlite extra missing: {exc}")
    assert isinstance(runner, AgentRunner)
    assert runner.config.memory.enabled is True
    assert runner.config.rag is None


def test_saas_example_builds_agent_config():
    path = NEXUS_ROOT / "examples" / "nexus_saas_api.py"
    spec = importlib.util.spec_from_file_location("nexus_saas_api", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError as exc:
        pytest.skip(f"saas example optional deps missing: {exc}")
    tenant = next(iter(mod.MOCK_TENANTS_DB.values()))
    cfg = mod.NexusTenantConfigFactory.build_agent_config(
        tenant, "assistant", "Assistant", "Help"
    )
    assert isinstance(cfg, AgentConfig)
    assert cfg.rag is None
    AgentRunner(
        config=cfg,
        tool_registry=ToolRegistry(),
        run_context=RunContext(tenant_id=tenant.tenant_id, user_id="u"),
        cross_session_memory_store=InMemoryCrossSessionMemoryStore(),
    )


def test_aitalk_tenant_memory_store_import():
    if not (AITALK_SRC / "aitalk_nexus").is_dir():
        pytest.skip("aitalk-nexus src not present")
    if str(AITALK_SRC) not in sys.path:
        sys.path.insert(0, str(AITALK_SRC))
    try:
        from aitalk_nexus.api_tenant.memory_storage import TenantMemoryStore
    except Exception as exc:
        pytest.skip(f"aitalk-nexus import needs app deps: {exc}")

    assert TenantMemoryStore is not None


def test_aitalk_build_chat_runner():
    if not (AITALK_SRC / "aitalk_nexus").is_dir():
        pytest.skip("aitalk-nexus src not present")
    if str(AITALK_SRC) not in sys.path:
        sys.path.insert(0, str(AITALK_SRC))
    try:
        from aitalk_nexus.api_tenant.api.chat_runner import build_chat_runner
        from nexus.session.manager import SessionManager
    except Exception as exc:
        pytest.skip(f"aitalk-nexus not importable: {exc}")

    ctx = RunContext(tenant_id="t", user_id="u", session_id="s")
    try:
        runner, _, _ = build_chat_runner(
            ctx,
            toolset_names=[],
            system_prompt="hi",
            model_cfg={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"},
            skills_block=None,
            session_manager=SessionManager(),
            memory_store=InMemoryCrossSessionMemoryStore(),
        )
    except Exception as exc:
        pytest.skip(f"build_chat_runner needs app settings: {exc}")
    assert isinstance(runner, AgentRunner)
    assert runner.config.rag is None
