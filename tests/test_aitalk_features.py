"""AITalkV2-style integration tests for new Nexus first-class features."""

from __future__ import annotations

import pytest

from nexus.config.agent import AgentConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import MemoryConfig, MemoryStoreConfig
from nexus.memory.cross_session_store import InMemoryCrossSessionMemoryStore
from nexus.memory.plugin import create_memory_plugin
from nexus.session.adapters.aitalk_chats import AiTalkChatsMemoryAdapter
from nexus.session.codec import DefaultSessionCodec
from nexus.session.manager import SessionManager
from nexus.session.models import AgentSession, ToolCallRecord, TurnRecord
from nexus.session.scope import SessionScope
from nexus.skills.config import SkillsConfig
from nexus.skills.manage_plugin import create_skill_manage_plugin
from nexus.skills.scope import SkillScopeConfig, build_skill_scope_resolver
from nexus.skills.store import FileSkillStore, InMemorySkillStore, build_learned_skills_block
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin
from nexus.tools.registry import ToolRegistry
from nexus.tools.toolsets import (
    Toolset,
    effective_tools,
    list_frontend_toolsets,
    resolve_toolset_tools,
)


@pytest.mark.asyncio
async def test_run_context_scope_and_services():
    ctx = RunContext(
        tenant_id="acme",
        company_id="42",
        user_id="u1",
        user_name="Ada",
        channel="web",
        is_cron=False,
    ).with_service("db", {"pool": True})
    scope = ctx.to_scope()
    assert scope.tenant_id == "acme"
    assert scope.company_id == "42"
    assert ctx.service("db")["pool"] is True
    assert ctx.should_persist is True
    ctx.is_subagent = True
    assert ctx.should_persist is False


@pytest.mark.asyncio
async def test_aitalk_chats_adapter_company_scoped():
    """Mirrors ankpal.AiTalkChats: tenant+chatId upsert, company filter."""
    adapter = AiTalkChatsMemoryAdapter()
    mgr = SessionManager(storage_adapter=adapter)
    scope = SessionScope(tenant_id="t1", company_id="9", user_id="7")
    session = await mgr.create_session(
        agent_id="aitalk",
        session_id="chat-1",
        scope=scope,
        user_name="Ada",
        title="GST help",
    )
    session.pinned = True
    session.attachment_ids = ["att-1"]
    await mgr.save_session(session)

    turn = TurnRecord(
        turn_index=0,
        user_message="Show GST",
        llm_messages=[{"role": "assistant", "content": "Sure"}],
        tool_calls=[
            ToolCallRecord(
                tc_id="TC1",
                tc_index=1,
                tool_name="reports.gst",
                call_id="call_abc",
                tool_input={"period": "FY25"},
                raw_response='{"ok": true}',
            )
        ],
    )
    await mgr.append_turn("chat-1", turn, scope=scope)

    loaded = await mgr.load_session(
        "chat-1",
        scope=SessionScope(tenant_id="t1", company_id="9"),
    )
    assert loaded is not None
    assert loaded.title == "GST help"
    assert loaded.pinned is True
    assert loaded.turns[0].tool_calls[0].call_id == "call_abc"

    # Wrong company must not see the chat
    missing = await mgr.load_session(
        "chat-1",
        scope=SessionScope(tenant_id="t1", company_id="99"),
    )
    assert missing is None

    row = adapter._rows["chat-1"]
    assert row["tenantId"] == "t1"
    assert row["companyId"] == "9"
    assert "chatJson" in row


@pytest.mark.asyncio
async def test_custom_session_codec_roundtrip():
    class SlimCodec:
        def dumps(self, session: AgentSession):
            return {
                "id": session.session_id,
                "turns": [
                    {"u": t.user_message, "a": t.llm_messages}
                    for t in session.turns
                ],
                "tenant": session.tenant_id,
                "company": session.company_id,
                "user": session.user_id,
                "agent": session.agent_id,
            }

        def loads(self, data, *, ctx=None):
            payload = data if isinstance(data, dict) else DefaultSessionCodec().loads(data)
            if "id" in payload and "turns" in payload and "agent" in payload:
                return AgentSession(
                    session_id=payload["id"],
                    agent_id=payload["agent"],
                    tenant_id=payload.get("tenant"),
                    company_id=payload.get("company"),
                    user_id=payload.get("user"),
                    turns=[
                        TurnRecord(
                            turn_index=i,
                            user_message=t.get("u"),
                            llm_messages=t.get("a") or [],
                        )
                        for i, t in enumerate(payload.get("turns") or [])
                    ],
                )
            return DefaultSessionCodec().loads(payload)

    adapter = AiTalkChatsMemoryAdapter(codec=SlimCodec())
    session = AgentSession(
        session_id="c1",
        agent_id="a",
        tenant_id="t",
        company_id="1",
        user_id="u",
        turns=[TurnRecord(turn_index=0, user_message="hi", llm_messages=[])],
    )
    await adapter.save_session(session)
    loaded = await adapter.load_session(
        "c1", scope=SessionScope(tenant_id="t", company_id="1")
    )
    assert loaded is not None
    assert loaded.turns[0].user_message == "hi"
    assert adapter._rows["c1"]["chatJson"]["id"] == "c1"


@pytest.mark.asyncio
async def test_memory_plugin_write_list_search():
    store = InMemoryCrossSessionMemoryStore()
    cfg = MemoryConfig(
        enabled=True,
        expose_tools=True,
        stores=[
            MemoryStoreConfig(name="user", inject="always", char_budget=1375),
            MemoryStoreConfig(name="memory", inject="always", char_budget=2200),
        ],
    )
    plugin = create_memory_plugin(store, cfg, agent_name="aitalk")
    ctx = RunContext(tenant_id="t", company_id="1", user_id="7")
    out = await plugin.write(key="preferred_language", value="Hindi", store="user", ctx=ctx)
    assert '"ok": true' in out.replace("'", '"') or '"ok": true' in out or "true" in out
    listed = await plugin.list_facts(store="user", ctx=ctx)
    assert "preferred_language" in listed
    searched = await plugin.search(query="Hindi", store="user", ctx=ctx)
    assert "preferred_language" in searched


@pytest.mark.asyncio
async def test_skill_store_scope_company_vs_user(tmp_path):
    company_resolver = build_skill_scope_resolver(
        SkillScopeConfig(keys=["tenant_id", "company_id"])
    )
    user_resolver = build_skill_scope_resolver(
        SkillScopeConfig(keys=["tenant_id", "company_id", "user_id"])
    )
    store = FileSkillStore(tmp_path / "skills", scope_keys=["tenant_id", "company_id"])
    ctx_a = RunContext(tenant_id="t", company_id="1", user_id="ada")
    ctx_b = RunContext(tenant_id="t", company_id="1", user_id="bob")
    scope = company_resolver.resolve(ctx_a)
    await store.upsert(
        scope,
        __import__("nexus.skills.store", fromlist=["SkillRecord"]).SkillRecord(
            name="report/always_group_by_branch",
            trigger="When user asks for a sales report",
            content="Always group by branch",
            source="learned",
        ),
    )
    # Same company, different users share the skill
    found_a = await store.search(company_resolver.resolve(ctx_a), "sales report", k=3)
    found_b = await store.search(company_resolver.resolve(ctx_b), "sales report", k=3)
    assert len(found_a) == 1
    assert len(found_b) == 1

    # Per-user store isolates
    user_store = InMemorySkillStore()
    await user_store.upsert(
        user_resolver.resolve(ctx_a),
        __import__("nexus.skills.store", fromlist=["SkillRecord"]).SkillRecord(
            name="ada_only",
            trigger="Ada quirks",
            content="Prefer short answers",
        ),
    )
    assert len(await user_store.list(user_resolver.resolve(ctx_a))) == 1
    assert len(await user_store.list(user_resolver.resolve(ctx_b))) == 0

    block = build_learned_skills_block(found_a)
    assert "always_group_by_branch" in block
    assert "Learned Skills" in block
    assert "Always group by branch" in block


@pytest.mark.asyncio
async def test_skill_manage_plugin_respects_persistable():
    store = InMemorySkillStore()
    resolver = build_skill_scope_resolver(SkillScopeConfig(keys=["tenant_id", "user_id"]))
    plugin = create_skill_manage_plugin(store, resolver)
    ctx = RunContext(tenant_id="t", user_id="u", is_cron=True)
    out = await plugin.upsert(
        name="skip_me", trigger="x", content="y", ctx=ctx
    )
    assert "skipped" in out
    assert await store.list(resolver.resolve(ctx)) == []


def test_frontend_toolsets_catalog_like_aitalk():
    toolsets = {
        "web_base": Toolset(
            name="web_base",
            visibility="hidden",
            includes=["memory"],
            tools=["reports.gst"],
        ),
        "memory": Toolset(
            name="memory",
            visibility="hidden",
            tools=["memory.write", "memory.search"],
        ),
        "bulk_scan": Toolset(
            name="bulk_scan",
            description="Bulk purchase-invoice scan",
            visibility="frontend",
            default_enabled=False,
            tools=["bulk.upload", "bulk.list"],
        ),
        "profile": Toolset(
            name="profile",
            description="Update saved profile",
            visibility="frontend",
            tools=["profile.manage"],
        ),
    }
    catalog = list_frontend_toolsets(toolsets)
    assert {c.toolset for c in catalog} == {"bulk_scan", "profile"}
    tools = effective_tools(
        base_toolsets=["web_base"],
        enabled_toolsets=["bulk_scan"],
        optional_toolsets=["bulk_scan", "profile"],
        toolsets=toolsets,
    )
    assert "reports.gst" in tools
    assert "memory.write" in tools
    assert "bulk.upload" in tools
    assert "profile.manage" not in tools
    assert "bulk.upload" in resolve_toolset_tools("bulk_scan", toolsets)


@pytest.mark.asyncio
async def test_client_tool_execution_metadata():
    @tool_plugin(name="ui")
    class UIPlugin:
        @tool(name="pick_file", execution="client", description="Pick a local file")
        def pick_file(self, pattern: str = "*") -> str:
            return "should not run on server"

    reg = ToolRegistry()
    reg.register_plugin(UIPlugin())
    assert reg.get_execution_mode("ui.pick_file") == "client"


@pytest.mark.asyncio
async def test_non_persistable_runner_skips_storage():
    from nexus.runner.agent_runner import AgentRunner

    adapter = AiTalkChatsMemoryAdapter()
    mgr = SessionManager(storage_adapter=adapter)
    ctx = RunContext(
        tenant_id="t",
        company_id="1",
        user_id="u",
        is_cron=True,
        persistable=False,
    )
    config = AgentConfig(
        name="cron_agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini"),
        persona=AgentPersonaConfig(role="Cron", goal="Run jobs"),
    )
    runner = AgentRunner(
        config=config,
        tool_registry=ToolRegistry(),
        storage_config=mgr,
        run_context=ctx,
    )
    session = await runner._get_or_create_session("cron-1")
    # create still saves via create_session — for cron we allow create but
    # _persist_turn must not write additional turns when non-persistable
    turn = TurnRecord(turn_index=0, user_message="tick", llm_messages=[])
    session2 = await runner._persist_turn(session, turn)
    assert len(session2.turns) == 1
    # append_turn was skipped; row may exist from create but turns empty in storage
    loaded = await mgr.load_session(
        "cron-1", scope=SessionScope(tenant_id="t", company_id="1", user_id="u")
    )
    # create_session saved empty session; persist_turn skipped — turns still empty on disk
    assert loaded is not None
    assert loaded.turns == []
