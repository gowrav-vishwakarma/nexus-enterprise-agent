"""NEXUS Framework — Multi-Tenant SaaS Example.

Demonstrates plan-based feature gating via **toolsets**, per-tenant storage,
cross-session user memory (``user_memory``), RCS, and agent group configurations
in a FastAPI environment. Chat history and durable facts are scoped to tenant +
user via ``X-Tenant-ID`` and ``X-User-ID``.

Tools are defined as flat ``@tool`` functions, grouped into named toolsets on a
shared ``ToolRegistry``, and selected per agent with ``AgentConfig.toolset``.
"""

from __future__ import annotations

import logging
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

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, SecretStr, Field

# ── NEXUS imports (validated against codebase) ────────────────────────────────
from nexus.config.agent import AgentConfig, AgentPersonaConfig, TurnConfig, AgentGroupConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import MemoryConfig
from nexus.memory.cross_session_store import CrossSessionMemoryStore
from nexus.persistence.factory import PersistenceBundle, PersistenceFactory
from nexus.config.rcs import RuntimeContextSummarizerConfig, ServerCompactorConfig
from nexus.config.storage import SessionStorageConfig
from nexus.skills.config import SkillsConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.session.manager import SessionManager
from nexus.session.scope import SessionScope
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry
from nexus.tools.decorators import tool
from nexus.realtime.input import UserInput
from nexus.realtime.multimodal.runner import VisionAgentRunner

logger = logging.getLogger(__name__)


# =============================================================================
# 1. FLAT TOOL DEFINITIONS (Stubs replacing missing builtins)
# =============================================================================

@tool(name="web_search", description="Search the web for a query.")
def web_search(query: str) -> str:
    return f"Web search result for: '{query}' - found framework releases."


@tool(name="database_query", description="Query the company database.")
def database_query(sql: str) -> str:
    return f"Database result: queried '{sql}' (returned 0 rows)."


@tool(name="calendar_events", description="Get upcoming calendar events.")
def calendar_events() -> str:
    return "Calendar: No upcoming events found."


def register_saas_toolsets(registry: ToolRegistry) -> ToolRegistry:
    """Register the SaaS demo tools and define plan-tier toolsets."""
    registry.add_toolset(
        "web_search",
        [web_search],
        description="Web search capability",
    )
    registry.add_toolset(
        "database",
        [database_query],
        description="Database query capability",
    )
    registry.add_toolset(
        "calendar",
        [calendar_events],
        description="Calendar lookup capability",
    )
    registry.add_toolset(
        "saas_starter",
        includes=["web_search"],
        description="Starter plan toolset",
    )
    registry.add_toolset(
        "saas_pro",
        includes=["web_search", "database", "calendar"],
        description="Pro plan toolset",
    )
    registry.add_toolset(
        "saas_enterprise",
        includes=["web_search", "database", "calendar"],
        description="Enterprise plan toolset",
    )
    return registry


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
    memory_enabled: bool

    # Tools: names of toolsets this plan may use. The first entry is the default
    # toolset when a caller requests one that is not allowed.
    allowed_toolsets: list[str]
    default_toolset: Optional[str] = None

    # Skills (global only in phase 1; tenant/user skills are future)
    skills_enabled: bool

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
        memory_enabled=False,
        allowed_toolsets=[],
        default_toolset=None,
        skills_enabled=False,
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
        memory_enabled=True,
        allowed_toolsets=["saas_starter"],
        default_toolset="saas_starter",
        skills_enabled=False,
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
        memory_enabled=True,
        allowed_toolsets=["saas_starter", "saas_pro", "web_search", "database", "calendar"],
        default_toolset="saas_pro",
        skills_enabled=True,
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
        memory_enabled=True,
        allowed_toolsets=["saas_starter", "saas_pro", "saas_enterprise", "web_search", "database", "calendar"],
        default_toolset="saas_enterprise",
        skills_enabled=True,
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
    custom_toolsets: list[str] = []

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
    SHARED_PG_DSN: SecretStr = SecretStr("postgresql://user:pass@localhost:5432/shared_db")

    # Custom LLM endpoint (LiteLLM proxy, LM Studio, or any OpenAI-compatible server)
    NEXUS_LLM_PROVIDER: str = os.getenv("NEXUS_LLM_PROVIDER", "openai")
    NEXUS_LLM_BASE_URL: str = os.getenv("NEXUS_LLM_BASE_URL", "")
    NEXUS_LLM_API_KEY: str = os.getenv("NEXUS_LLM_API_KEY", "")
    NEXUS_LLM_MODEL: str = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")

    @classmethod
    def _resolve_custom_llm_env(cls) -> tuple[str, str, str, str]:
        """Return (provider, base_url, api_key, model) from NEXUS_LLM_* or legacy LM_STUDIO_*."""
        base_url = os.getenv("NEXUS_LLM_BASE_URL", "")
        api_key = os.getenv("NEXUS_LLM_API_KEY", "")
        model = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")
        provider = os.getenv("NEXUS_LLM_PROVIDER", "openai")

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
        # Priority: platform custom endpoint (NEXUS_LLM_*) > tenant BYOK > plan defaults
        provider, base_url, api_key, model = cls._resolve_custom_llm_env()
        if base_url:
            return LLMProviderConfig(
                provider=provider,  # type: ignore[arg-type]
                model=model,
                api_key=SecretStr(api_key) if api_key else SecretStr("not-needed"),
                base_url=base_url,
                context_window_tokens=limits.context_window_tokens,
            )

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
            from nexus.storage.paths import get_data_root

            return SessionStorageConfig(
                adapter="sqlite",
                adapter_config={
                    "data_root": str(get_data_root()),
                    "tenant_scoped": True,
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
                    "schema_mode": os.getenv("NEXUS_PG_SCHEMA_MODE", "managed"),
                    "auto_migrate": os.getenv("NEXUS_PG_AUTO_MIGRATE", "false").lower() == "true",
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
        toolset: Optional[str] = None,
    ) -> AgentConfig:
        limits = PLAN_LIMITS[tenant.plan]
        llm = cls.build_llm_config(tenant, limits)

        # Resolve the requested toolset against the plan's allow-list. If the
        # caller asks for something not allowed (or asks for None), fall back
        # to the plan's default toolset.
        if toolset and toolset in limits.allowed_toolsets:
            resolved_toolset = toolset
        else:
            resolved_toolset = limits.default_toolset

        if tenant.system_prompt_prefix:
            role = f"{tenant.system_prompt_prefix}\n{role}"

        return AgentConfig(
            name=name,
            llm=llm,
            persona=AgentPersonaConfig(role=role, goal=goal),
            turns=TurnConfig(max_turns=limits.max_turns, max_tool_calls_per_turn=limits.max_tool_calls_per_turn),
            rcs=cls.build_rcs_config(tenant, limits, llm),
            memory=MemoryConfig(enabled=limits.memory_enabled),
            toolset=resolved_toolset,
            skills=SkillsConfig(
                enabled=limits.skills_enabled,
                activation_mode="auto",
                allow_tenant_skills=False,
                allow_user_skills=False,
                allow_scripts=False,
            ),
        )


# =============================================================================
# 5. FASTAPI APP & RESOLVERS
# =============================================================================

app = FastAPI(title="Nexus SaaS API")


@app.on_event("startup")
async def log_custom_llm_config() -> None:
    provider, base_url, _, model = NexusTenantConfigFactory._resolve_custom_llm_env()
    if base_url:
        logger.info(
            "Custom LLM endpoint configured: provider=%s base_url=%s model=%s",
            provider,
            base_url,
            model,
        )


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
register_saas_toolsets(SHARED_TOOL_REGISTRY)


class TenantPersistenceResolver:
    """Example resolver: map tenant record → SessionStorageConfig (override in production)."""

    def resolve_storage_config(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
    ) -> SessionStorageConfig:
        tenant_rec = MOCK_TENANTS_DB.get(tenant_id or "")
        if tenant_rec is None:
            return SessionStorageConfig(adapter="memory")
        limits = PLAN_LIMITS[tenant_rec.plan]
        return NexusTenantConfigFactory.build_storage_config(tenant_rec, limits)

    def resolve_bundle(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
    ) -> Optional[PersistenceBundle]:
        return None


TENANT_PERSISTENCE_RESOLVER = TenantPersistenceResolver()

# In-memory adapters are per-instance; reuse one SessionManager per tenant so
# chat and session GET endpoints see the same data within a running process.
_SESSION_MANAGERS: dict[str, SessionManager] = {}


def get_shared_session_manager(
    tenant_id: str,
    storage_config: SessionStorageConfig,
) -> SessionManager:
    if tenant_id not in _SESSION_MANAGERS:
        _SESSION_MANAGERS[tenant_id] = SessionManager.from_config(storage_config)
    return _SESSION_MANAGERS[tenant_id]


def get_persistence_bundle(tenant_id: str, user_id: str) -> PersistenceBundle:
    return PersistenceFactory.from_resolver(
        TENANT_PERSISTENCE_RESOLVER,
        tenant_id,
        user_id,
    )


# ── Request / Response schemas ───────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = False


# Storage is per-tenant runtime wiring on the runner/orchestrator, not AgentConfig.


@app.post("/v1/chat")
async def chat(
    body: ChatRequest,
    tenant_ctx: ResolvedTenant = Depends(get_resolved_tenant),
    # Defaults to demo-user when omitted (fine for local demos). Production apps
    # should send a stable id per signed-in user — chat history and cross-session
    # user_memory are scoped to tenant + user, not tenant alone.
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
        toolset="saas_pro",
    )

    run_context = RunContext(
        tenant_id=tenant_ctx.tenant_id,
        user_id=x_user_id,
        session_id=body.session_id or str(uuid4()),
    )

    persistence = get_persistence_bundle(tenant_ctx.tenant_id, x_user_id)

    session_manager = get_shared_session_manager(
        tenant_ctx.tenant_id,
        tenant_ctx.storage_config,
    )

    runner = AgentRunner(
        config=agent_config,
        tool_registry=SHARED_TOOL_REGISTRY,
        storage_config=session_manager,
        run_context=run_context,
        cross_session_memory_store=persistence.cross_session_memory_store,
    )

    use_stream = body.stream or agent_config.stream_output

    if use_stream:
        async def event_generator():
            async for event in runner.run_stream(
                user_message=body.message,
                session_id=run_context.session_id,
                stream=True if body.stream else None,
            ):
                yield f"data: {event.model_dump_json()}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    result = await runner.run(
        user_message=body.message,
        session_id=run_context.session_id,
        stream=False if body.stream is False else None,
    )

    return {
        "session_id": result.session_id,
        "response": result.final_response,
        "turns_used": result.turns_used,
        "tokens_saved_by_rcs": result.total_tokens_saved_by_rcs,
        "plan": tenant_ctx.plan,
        "user_id": x_user_id,
    }


@app.post("/v1/chat/vision")
async def chat_vision(
    message: str = Form(""),
    image: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    tenant_ctx: ResolvedTenant = Depends(get_resolved_tenant),
    x_user_id: str = Header(default="demo-user", alias="X-User-ID"),
):
    """Vision chat: send an image (multipart) plus optional text.

    Separate route from ``/v1/chat`` so the text API is untouched. Uses the same
    tenant scoping, persistence, and session conventions. Requires a vision-
    capable LLM model on the tenant's plan (e.g. gpt-4o).
    """
    tenant_rec = MOCK_TENANTS_DB[tenant_ctx.tenant_id]

    agent_config = NexusTenantConfigFactory.build_agent_config(
        tenant=tenant_rec,
        name="vision_assistant",
        role="Vision Analyst",
        goal="Describe and reason about images the user shares.",
        toolset=None,
    )

    run_context = RunContext(
        tenant_id=tenant_ctx.tenant_id,
        user_id=x_user_id,
        session_id=session_id or str(uuid4()),
    )

    persistence = get_persistence_bundle(tenant_ctx.tenant_id, x_user_id)
    session_manager = get_shared_session_manager(
        tenant_ctx.tenant_id,
        tenant_ctx.storage_config,
    )

    vision_runner = VisionAgentRunner(
        config=agent_config,
        tool_registry=SHARED_TOOL_REGISTRY,
        storage_config=session_manager,
        run_context=run_context,
        cross_session_memory_store=persistence.cross_session_memory_store,
    )

    raw = await image.read()
    user_input = UserInput.from_image_bytes(
        raw,
        text=message,
        mime_type=image.content_type or "image/png",
    )

    result = await vision_runner.run(
        user_input,
        session_id=run_context.session_id,
        stream=False,
    )

    return {
        "session_id": result.session_id,
        "response": result.final_response,
        "turns_used": result.turns_used,
        "plan": tenant_ctx.plan,
        "user_id": x_user_id,
    }


@app.get("/v1/sessions/{session_id}")
async def get_session(
    session_id: str,
    tenant_ctx: ResolvedTenant = Depends(get_resolved_tenant),
    x_user_id: str = Header(default="demo-user", alias="X-User-ID"),
):
    """Return the persisted chat thread JSON (turns, tool calls, RCS totals).

    Durable user facts (``user_memory``) live in the cross-session store, not in
    this session payload. See ``GET`` handlers that pass ``user_id`` for scoping.
    """
    manager = get_shared_session_manager(tenant_ctx.tenant_id, tenant_ctx.storage_config)
    session = await manager.load_session(
        session_id,
        scope=SessionScope(tenant_id=tenant_ctx.tenant_id, user_id=x_user_id),
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump()


@app.get("/v1/sessions/{root_session_id}/group")
async def get_session_group(
    root_session_id: str,
    tenant_ctx: ResolvedTenant = Depends(get_resolved_tenant),
    x_user_id: str = Header(default="demo-user", alias="X-User-ID"),
    pattern: str = Query(default="auto"),
    member_order: Optional[str] = Query(
        default=None,
        description="Comma-separated member names for pipeline ordering",
    ),
    include_internal: bool = Query(default=False),
):
    """Load all sub-agent sessions for a root chat session id as a nested tree."""
    manager = get_shared_session_manager(tenant_ctx.tenant_id, tenant_ctx.storage_config)
    order = [m.strip() for m in member_order.split(",")] if member_order else None
    view = await manager.load_session_group(
        root_session_id,
        scope=SessionScope(tenant_id=tenant_ctx.tenant_id, user_id=x_user_id),
        pattern=pattern,  # type: ignore[arg-type]
        member_order=order,
        include_internal=include_internal,
    )
    return view.model_dump()


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
        toolset="web_search",
    )

    analyst_cfg = NexusTenantConfigFactory.build_agent_config(
        tenant=tenant_rec,
        name="analyst",
        role="Analyst",
        goal="Analyze data and formulate structure.",
        toolset="database",
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

    session_manager = get_shared_session_manager(
        tenant_ctx.tenant_id,
        tenant_ctx.storage_config,
    )

    orchestrator = AgentOrchestrator(
        config=group_config,
        tool_registry=SHARED_TOOL_REGISTRY,
        storage_config=session_manager,
        run_context=run_context,
        cross_session_memory_store=get_persistence_bundle(
            tenant_ctx.tenant_id, x_user_id
        ).cross_session_memory_store,
    )

    use_stream = body.stream or group_config.stream_output

    if use_stream:
        async def group_event_generator():
            async for event in orchestrator.run_stream(
                user_message=body.message,
                session_id=run_context.session_id,
                stream=True if body.stream else None,
            ):
                yield f"data: {event.model_dump_json()}\n\n"

        return StreamingResponse(group_event_generator(), media_type="text/event-stream")

    result = await orchestrator.run(
        user_message=body.message,
        session_id=run_context.session_id,
        stream=False if body.stream is False else None,
    )

    return {
        "session_id": result.session_id,
        "response": result.final_response,
        "status": result.status,
        "turns_used": result.turns_used,
        "tokens_saved_by_rcs": result.total_tokens_saved_by_rcs,
    }
