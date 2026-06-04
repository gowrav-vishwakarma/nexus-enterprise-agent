"""NEXUS Framework — Multi-Tenant SaaS Example.

Demonstrates plan-based feature gating, per-tenant storage,
memory, RCS, and agent group configurations in a FastAPI environment.
"""

from __future__ import annotations

import os
import warnings
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

# Load .env file so env vars are available for LLM config
try:
    from dotenv import load_dotenv
    import pathlib
    # Load .env from project root (parent of examples/)
    env_path = pathlib.Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass  # python-dotenv not installed, skip

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, SecretStr, Field

# ── NEXUS imports (validated against codebase) ────────────────────────────────
from nexus.config.agent import AgentConfig, AgentPersonaConfig, TurnConfig, AgentGroupConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import EntityMemoryConfig, MemoryConfig, UserMemoryConfig, WorkingMemoryConfig
from nexus.memory.user_store import SQLiteUserMemoryStore
from nexus.config.rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from nexus.config.storage import SessionStorageConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry
from nexus.tools.decorators import tool, tool_plugin


# =============================================================================
# 1. TOOL PLUGINS DEFINITIONS (Stubs replacing missing builtins)
# =============================================================================

@tool_plugin(name="web_search")
class WebSearchPlugin:
    @tool(name="search")
    def search(self, query: str) -> str:
        """Search the web for a query."""
        return f"Web search result for: '{query}' - found framework releases."


@tool_plugin(name="database")
class DatabasePlugin:
    @tool(name="query")
    def query(self, sql: str) -> str:
        """Query the company database."""
        return f"Database result: queried '{sql}' (returned 0 rows)."


@tool_plugin(name="calendar")
class CalendarPlugin:
    @tool(name="get_events")
    def get_events(self) -> str:
        """Get upcoming calendar events."""
        return "Calendar: No upcoming events found."


# =============================================================================
# 2. PLAN DEFINITIONS & LIMITS
# =============================================================================

class Plan(str, Enum):
    FREE       = "free"
    STARTER    = "starter"
    PRO        = "pro"
    ENTERPRISE = "enterprise"


class PlanLimits(BaseModel):
    # Conversation
    max_turns: int
    max_tool_calls_per_turn: int
    max_sessions: int
    session_ttl_days: int

    # Agents / Group Orchestration
    max_agents_in_group: int
    allow_multi_agent: bool
    allowed_patterns: list[str]

    # Context & RCS
    rcs_enabled: bool
    rcs_fallback_compactor: bool
    context_window_tokens: int

    # Storage Adapter to use
    storage_adapter: str

    # Memory features
    entity_memory: bool
    working_memory: bool

    # Tools
    allowed_tool_plugins: list[str]

    # LLM Options
    use_tenant_llm_key: bool
    default_model: str
    allow_model_override: bool


PLAN_LIMITS: dict[Plan, PlanLimits] = {
    Plan.FREE: PlanLimits(
        max_turns=3,
        max_tool_calls_per_turn=1,
        max_sessions=5,
        session_ttl_days=1,
        max_agents_in_group=1,
        allow_multi_agent=False,
        allowed_patterns=["solo"],
        rcs_enabled=False,
        rcs_fallback_compactor=False,
        context_window_tokens=4000,
        storage_adapter="memory",
        entity_memory=False,
        working_memory=False,
        allowed_tool_plugins=[],
        use_tenant_llm_key=False,
        default_model="gpt-4o-mini",
        allow_model_override=False,
    ),
    Plan.STARTER: PlanLimits(
        max_turns=8,
        max_tool_calls_per_turn=3,
        max_sessions=50,
        session_ttl_days=30,
        max_agents_in_group=1,
        allow_multi_agent=False,
        allowed_patterns=["solo"],
        rcs_enabled=False,
        rcs_fallback_compactor=False,
        context_window_tokens=8000,
        storage_adapter="sqlite",
        entity_memory=True,
        working_memory=False,
        allowed_tool_plugins=["web_search"],
        use_tenant_llm_key=False,
        default_model="gpt-4o-mini",
        allow_model_override=False,
    ),
    Plan.PRO: PlanLimits(
        max_turns=20,
        max_tool_calls_per_turn=8,
        max_sessions=500,
        session_ttl_days=90,
        max_agents_in_group=5,
        allow_multi_agent=True,
        allowed_patterns=["pipeline", "supervisor"],
        rcs_enabled=True,
        rcs_fallback_compactor=False,
        context_window_tokens=32000,
        storage_adapter="postgresql",
        entity_memory=True,
        working_memory=True,
        allowed_tool_plugins=["web_search", "database", "calendar"],
        use_tenant_llm_key=True,
        default_model="gpt-4o",
        allow_model_override=True,
    ),
    Plan.ENTERPRISE: PlanLimits(
        max_turns=100,
        max_tool_calls_per_turn=20,
        max_sessions=99999,
        session_ttl_days=365,
        max_agents_in_group=20,
        allow_multi_agent=True,
        allowed_patterns=["pipeline", "supervisor", "swarm", "parallel"],
        rcs_enabled=True,
        rcs_fallback_compactor=True,
        context_window_tokens=128000,
        storage_adapter="postgresql",
        entity_memory=True,
        working_memory=True,
        allowed_tool_plugins=["web_search", "database", "calendar", "custom"],
        use_tenant_llm_key=True,
        default_model="claude-3-5-sonnet-20241022",
        allow_model_override=True,
    ),
}


# =============================================================================
# 3. TENANT & STORAGE PROFILES
# =============================================================================

class TenantRecord(BaseModel):
    tenant_id: str
    name: str
    plan: Plan

    # Bring-your-own-key settings
    openai_api_key: Optional[SecretStr] = None
    anthropic_api_key: Optional[SecretStr] = None

    # Storage isolated configuration
    custom_db_dsn: Optional[SecretStr] = None
    schema_name: Optional[str] = None
    isolation_mode: str = "shared_schema"  # "shared_schema" | "dedicated_schema" | "dedicated_db"

    # Customization & Overrides
    system_prompt_prefix: Optional[str] = None
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    custom_tool_plugins: list[str] = []

    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


class ResolvedTenant(BaseModel):
    tenant_id: str
    display_name: str
    plan: Plan
    storage_config: SessionStorageConfig

    class Config:
        arbitrary_types_allowed = True


# =============================================================================
# 4. CONFIG FACTORY
# =============================================================================

class NexusTenantConfigFactory:
    PLATFORM_OPENAI_KEY: SecretStr = SecretStr(os.getenv("PLATFORM_OPENAI_KEY", "mock-platform-key"))
    PLATFORM_ANTHROPIC_KEY: SecretStr = SecretStr(os.getenv("PLATFORM_ANTHROPIC_KEY", "mock-platform-key"))
    SHARED_SQLITE_PATH: str = "./shared_sessions.db"
    SHARED_PG_DSN: SecretStr = SecretStr("postgresql://user:pass@localhost:5432/shared_db")

    # Custom LLM endpoint (LiteLLM proxy, LM Studio, or any OpenAI-compatible server)
    NEXUS_LLM_PROVIDER: str = os.getenv("NEXUS_LLM_PROVIDER", "openai")
    NEXUS_LLM_BASE_URL: str = os.getenv("NEXUS_LLM_BASE_URL", "")
    NEXUS_LLM_API_KEY: str = os.getenv("NEXUS_LLM_API_KEY", "")
    NEXUS_LLM_MODEL: str = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")

    @classmethod
    def _resolve_custom_llm_env(cls) -> tuple[str, str, str, str]:
        """Return (provider, base_url, api_key, model) from NEXUS_LLM_* or legacy LM_STUDIO_*."""
        base_url = cls.NEXUS_LLM_BASE_URL
        api_key = cls.NEXUS_LLM_API_KEY
        model = cls.NEXUS_LLM_MODEL
        provider = cls.NEXUS_LLM_PROVIDER

        legacy_base = os.getenv("LM_STUDIO_BASE_URL", "")
        if not base_url and legacy_base:
            warnings.warn(
                "LM_STUDIO_BASE_URL is deprecated; use NEXUS_LLM_BASE_URL instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            base_url = legacy_base
            api_key = api_key or os.getenv("LM_STUDIO_API_KEY", "")
            model = os.getenv("LM_STUDIO_MODEL", model) if os.getenv("LM_STUDIO_MODEL") else model

        return provider, base_url, api_key, model

    @classmethod
    def build_llm_config(cls, tenant: TenantRecord, limits: PlanLimits) -> LLMProviderConfig:
        # Priority: tenant-specific LLM config > custom endpoint env vars > plan defaults
        if limits.use_tenant_llm_key and limits.allow_model_override:
            if tenant.preferred_provider == "anthropic" and tenant.anthropic_api_key:
                return LLMProviderConfig(
                    provider="anthropic",
                    model=tenant.preferred_model or limits.default_model,
                    api_key=tenant.anthropic_api_key,
                    context_window_tokens=limits.context_window_tokens,
                )
            elif tenant.openai_api_key:
                return LLMProviderConfig(
                    provider="openai",
                    model=tenant.preferred_model or limits.default_model,
                    api_key=tenant.openai_api_key,
                    context_window_tokens=limits.context_window_tokens,
                )

        provider, base_url, api_key, model = cls._resolve_custom_llm_env()
        if base_url:
            return LLMProviderConfig(
                provider=provider,  # type: ignore[arg-type]
                model=model,
                api_key=SecretStr(api_key) if api_key else SecretStr("not-needed"),
                base_url=base_url,
                context_window_tokens=limits.context_window_tokens,
            )

        # Ultimate fallback: use plan defaults with platform key
        return LLMProviderConfig(
            provider="openai",
            model=limits.default_model,
            api_key=cls.PLATFORM_OPENAI_KEY,
            context_window_tokens=limits.context_window_tokens,
        )

    @classmethod
    def build_storage_config(cls, tenant: TenantRecord, limits: PlanLimits) -> SessionStorageConfig:
        if limits.storage_adapter == "memory":
            return SessionStorageConfig(
                adapter="memory",
                adapter_config={
                    "max_sessions": limits.max_sessions,
                },
            )

        if limits.storage_adapter == "sqlite":
            return SessionStorageConfig(
                adapter="sqlite",
                adapter_config={
                    "db_path": cls.SHARED_SQLITE_PATH,
                    "table_prefix": f"t_{tenant.tenant_id}_",
                },
            )

        if limits.storage_adapter == "postgresql":
            if tenant.isolation_mode == "dedicated_db" and tenant.custom_db_dsn:
                dsn = tenant.custom_db_dsn
                schema = "public"
            elif tenant.isolation_mode == "dedicated_schema":
                dsn = cls.SHARED_PG_DSN
                schema = tenant.schema_name or f"co_{tenant.tenant_id}"
            else:
                dsn = cls.SHARED_PG_DSN
                schema = "tenant_shared"

            return SessionStorageConfig(
                adapter="postgresql",
                adapter_config={
                    "dsn": dsn.get_secret_value(),
                    "schema": schema,
                    "table_prefix": "nexus_",
                },
            )

        raise ValueError(f"Unsupported storage adapter: {limits.storage_adapter}")

    @classmethod
    def build_rcs_config(cls, tenant: TenantRecord, limits: PlanLimits, llm: LLMProviderConfig) -> RuntimeContextSummarizerConfig:
        if not limits.rcs_enabled:
            return RuntimeContextSummarizerConfig(enabled=False)

        compactor = ServerCompactorConfig(enabled=False)
        if limits.rcs_fallback_compactor:
            compactor = ServerCompactorConfig(
                enabled=True,
                trigger_token_threshold=int(limits.context_window_tokens * 0.75),
                compact_oldest_n_tcs=3,
                compactor_llm=llm,
                max_compacted_summary_tokens=150,
            )

        return RuntimeContextSummarizerConfig(
            enabled=True,
            tc_tag_format="[TC{n}]",
            fallback_compactor=compactor,
        )

    @classmethod
    def build_agent_config(
        cls,
        tenant: TenantRecord,
        name: str,
        role: str,
        goal: str,
        tool_plugins: list[str]
    ) -> AgentConfig:
        limits = PLAN_LIMITS[tenant.plan]
        llm = cls.build_llm_config(tenant, limits)

        allowed_tools = [p for p in tool_plugins if p in limits.allowed_tool_plugins]

        if tenant.system_prompt_prefix:
            role = f"{tenant.system_prompt_prefix}\n{role}"

        return AgentConfig(
            name=name,
            llm=llm,
            persona=AgentPersonaConfig(role=role, goal=goal),
            turns=TurnConfig(max_turns=limits.max_turns, max_tool_calls_per_turn=limits.max_tool_calls_per_turn),
            rcs=cls.build_rcs_config(tenant, limits, llm),
            memory=MemoryConfig(
                enabled=limits.entity_memory or limits.working_memory,
                entity=EntityMemoryConfig(enabled=limits.entity_memory),
                working=WorkingMemoryConfig(enabled=limits.working_memory),
                user=UserMemoryConfig(enabled=limits.entity_memory),
            ),
            tool_plugins=allowed_tools,
        )


# =============================================================================
# 5. FASTAPI APP & RESOLVERS
# =============================================================================

app = FastAPI(title="Nexus SaaS API")

# InMemory DB mock for tenants
MOCK_TENANTS_DB: dict[str, TenantRecord] = {
    "free_tenant_1": TenantRecord(
        tenant_id="free_tenant_1",
        name="Free Demo Co",
        plan=Plan.FREE
    ),
    "pro_tenant_1": TenantRecord(
        tenant_id="pro_tenant_1",
        name="Pro Analytics Inc",
        plan=Plan.PRO,
        # No fake API key — falls through to NEXUS_LLM_* env vars (custom endpoint)
        isolation_mode="dedicated_schema",
        schema_name="co_pro_tenant_1",
    )
}


async def get_resolved_tenant(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
) -> ResolvedTenant:
    tenant_rec = MOCK_TENANTS_DB.get(x_tenant_id)
    if not tenant_rec or not tenant_rec.is_active:
        raise HTTPException(status_code=401, detail="Tenant registration inactive or invalid.")

    limits = PLAN_LIMITS[tenant_rec.plan]
    storage_config = NexusTenantConfigFactory.build_storage_config(tenant_rec, limits)

    return ResolvedTenant(
        tenant_id=tenant_rec.tenant_id,
        display_name=tenant_rec.name,
        plan=tenant_rec.plan,
        storage_config=storage_config,
    )


# Construct shared tool registry
SHARED_TOOL_REGISTRY = ToolRegistry()
SHARED_TOOL_REGISTRY.register_plugin(WebSearchPlugin())
SHARED_TOOL_REGISTRY.register_plugin(DatabasePlugin())
SHARED_TOOL_REGISTRY.register_plugin(CalendarPlugin())

SHARED_USER_MEMORY_STORE = SQLiteUserMemoryStore(db_path="./shared_user_memory.db")


# ── Request / Response schemas ───────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


# Storage is per-tenant runtime wiring on the runner/orchestrator, not AgentConfig.


@app.post("/v1/chat")
async def chat(
    body: ChatRequest,
    tenant_ctx: ResolvedTenant = Depends(get_resolved_tenant),
    x_user_id: str = Header(default="demo-user", alias="X-User-ID"),
):
    # Fetch database record for detailed options
    tenant_rec = MOCK_TENANTS_DB[tenant_ctx.tenant_id]

    # Dynamically build AgentConfig fully gated by plan constraints
    agent_config = NexusTenantConfigFactory.build_agent_config(
        tenant=tenant_rec,
        name="primary_assistant",
        role="Senior Executive Assistant",
        goal="Perform analysis tasks accurately using available tools.",
        tool_plugins=["web_search", "database", "calendar"]
    )

    run_context = RunContext(
        tenant_id=tenant_ctx.tenant_id,
        user_id=x_user_id,
        session_id=body.session_id or str(uuid4()),
    )

    runner = AgentRunner(
        config=agent_config,
        tool_registry=SHARED_TOOL_REGISTRY,
        storage_config=tenant_ctx.storage_config,
        run_context=run_context,
        user_memory_store=SHARED_USER_MEMORY_STORE,
    )

    result = await runner.run(
        user_message=body.message,
        session_id=run_context.session_id,
    )

    return {
        "session_id": result.session_id,
        "response": result.final_response,
        "turns_used": result.turns_used,
        "tokens_saved_by_rcs": result.total_tokens_saved_by_rcs,
        "plan": tenant_ctx.plan,
        "user_id": x_user_id,
    }


@app.post("/v1/multi-agent/run")
async def run_multi_agent_group(
    body: ChatRequest,
    tenant_ctx: ResolvedTenant = Depends(get_resolved_tenant),
    x_user_id: str = Header(default="demo-user", alias="X-User-ID"),
):
    if tenant_ctx.plan not in (Plan.PRO, Plan.ENTERPRISE):
        raise HTTPException(
            status_code=403,
            detail=f"Multi-agent groups require PRO or ENTERPRISE. Current: {tenant_ctx.plan}"
        )

    tenant_rec = MOCK_TENANTS_DB[tenant_ctx.tenant_id]
    limits = PLAN_LIMITS[tenant_rec.plan]

    # Build individual configs
    researcher_cfg = NexusTenantConfigFactory.build_agent_config(
        tenant=tenant_rec,
        name="researcher",
        role="Researcher",
        goal="Gather detailed information using search.",
        tool_plugins=["web_search"]
    )

    analyst_cfg = NexusTenantConfigFactory.build_agent_config(
        tenant=tenant_rec,
        name="analyst",
        role="Analyst",
        goal="Analyze data and formulate structure.",
        tool_plugins=["database"]
    )

    # In Nexus, AgentGroupConfig directly accepts configurations of sub-agents/groups in `members`
    group_config = AgentGroupConfig(
        name="research_pipeline",
        pattern="pipeline",
        members=[researcher_cfg, analyst_cfg],
        max_turns=limits.max_turns,
        rcs=NexusTenantConfigFactory.build_rcs_config(
            tenant_rec, limits, NexusTenantConfigFactory.build_llm_config(tenant_rec, limits)
        )
    )

    run_context = RunContext(
        tenant_id=tenant_ctx.tenant_id,
        user_id=x_user_id,
        session_id=body.session_id or str(uuid4()),
    )

    orchestrator = AgentOrchestrator(
        config=group_config,
        tool_registry=SHARED_TOOL_REGISTRY,
        storage_config=tenant_ctx.storage_config,
        run_context=run_context,
        user_memory_store=SHARED_USER_MEMORY_STORE,
    )

    result = await orchestrator.run(
        user_message=body.message,
        session_id=run_context.session_id,
    )

    return {
        "session_id": result.group_session_id,
        "response": result.final_response,
        "status": result.status,
        "turns_used": result.turns_used,
        "tokens_saved_by_rcs": result.total_tokens_saved_by_rcs,
    }
