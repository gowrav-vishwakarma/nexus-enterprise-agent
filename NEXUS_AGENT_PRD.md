# NEXUS AGENT FRAMEWORK — Product Requirements Document
**Version:** 2.0 | **Status:** Draft for LLM-assisted implementation  
**Purpose:** Complete specification for a SaaS-ready, context-efficient Python multi-agent framework  
**Key Update v2.0:** RCS mechanism corrected — LLM-driven inline summarization via `_context_updates`, zero extra LLM calls

---

## 1. EXECUTIVE SUMMARY & DESIGN PHILOSOPHY

### 1.1 Why Another Framework?

After studying LangGraph, CrewAI, AutoGen/AG2, OpenAI Agents SDK, Pydantic AI, Google ADK, Haystack, LlamaIndex Agents, and Semantic Kernel, the key gaps for production SaaS workloads are:

| Framework | Critical Gap |
|---|---|
| LangGraph | Heavily graph-coupled, complex state machine, hard to use in stateless HTTP |
| CrewAI | Role abstraction is opinionated; 3× token overhead on simple tasks; not SaaS-ready |
| AutoGen/AG2 | GroupChat bloat; every turn = full history LLM call; env-var dependent |
| OpenAI Agents SDK | Model-locked; no durable context management; no BYOM |
| Pydantic AI | Best-in-class type safety, but context compression is still manual |
| LangChain | Most token-efficient but architectural complexity; ecosystem churn risk |

**NEXUS** is built around one core principle: **context is the scarcest resource in long-horizon agentic tasks**. Every design decision is made to preserve, compress, or eliminate context waste — while remaining SaaS-ready (no global state, no env vars, fully per-request configurable).

### 1.2 Core Design Tenets

1. **Context-First Architecture** — Runtime Context Summarization (RCS) is a first-class citizen, not an afterthought.
2. **SaaS-Native** — Zero global state. All config passed per-call. FastAPI-ready.
3. **Overridable Everything** — Every prompt, every behavior, every storage backend is overridable via config.
4. **LLM-Driven Compression** — When RCS is on, the **agent LLM itself** writes the summaries inline as part of its next tool call via `_context_updates`. Zero extra LLM calls. The agent decides what is worth compressing and what to keep.
5. **Provider-Agnostic** — LLM provider is a config parameter, not a dependency.
6. **Pluggable Persistence** — Storage adapters for memory, file, SQLite, PostgreSQL, Redis — swappable without changing agent code.
7. **Type-Safe by Default** — Pydantic v2 models for all configs, messages, and tool IO.
8. **Observable** — Every turn, tool call, summarization event is emitted as a structured event for OpenTelemetry / custom sinks.

---

## 2. FRAMEWORK LANDSCAPE ANALYSIS (INFORMING DESIGN)

### 2.1 What We Steal From Each Framework

#### From LangGraph
- **Explicit state transitions** — Checkpoint-based turn state, decoupled from graph topology
- **Conditional routing** — Agent can route to sub-agents or exit based on state conditions
- **Reducer pattern** — For merging concurrent tool results into a single state snapshot

#### From CrewAI
- **Role/persona separation** — Agent has a `role`, `goal`, `backstory` prompt-block system
- **Task-level delegation** — A parent agent can spawn child agents with scoped context
- **Layered memory** — Short-term (turn buffer), long-term (vector), entity (key facts)

#### From Pydantic AI
- **Type-safe tool registration** — `@agent.tool` decorator with automatic Pydantic validation
- **Dependency injection** — `RunContext[Deps]` pattern for injecting per-request services
- **Structured output** — `result_type` forces LLM to return validated Pydantic models
- **Durable execution hooks** — State can be checkpointed and resumed

#### From AutoGen/AG2
- **Conversation termination conditions** — Configurable `max_turns`, `stop_on_keywords`, `stop_on_result_type`
- **Human-in-the-loop** — `HumanProxy` agent type that pauses for external input

#### From OpenAI Agents SDK
- **Explicit handoffs** — `transfer_to_agent(name)` as a first-class tool, not magic
- **Guardrails** — Input/output validators that run outside the main agent loop

#### From Haystack
- **Pipeline composability** — Agents can be wired as pipeline stages for batch processing

#### From Microsoft Agent Framework / Semantic Kernel
- **Plugin system** — Tools are grouped into "plugins" (namespaced toolsets)
- **Planner separation** — Planning step is separate from execution step

#### From Gowrav Vishwakarma's Inline Summarization Pattern
- **`_context_updates` injected into every tool** — Agent returns summaries of old TC results inside its next tool call
- **Zero extra LLM calls** — Compression happens inline, same LLM, same turn
- **Agent-decides-what-to-compress** — LLM knows best which results are still needed in full
- **TC tagging to signal compressibility** — Tagged results are candidates; already-compressed results lose the tag and become normal context

### 2.2 The Context Window Problem (Research Synthesis)

Research shows four dominant strategies:

1. **Bulk summarization** (LangChain rolling summary) — extra LLM call generates a full-history summary
2. **Observation masking** (SWE-agent) — simply drop older tool results, risks losing key facts
3. **Server-side selective compression** (ACON, SUPO) — server calls a compressor LLM per tool result
4. **LLM-inline selective compression** (Gowrav pattern) — agent writes summaries of old results inside its next tool call arguments; **zero extra LLM calls**

**NEXUS adopts strategy 4 as primary**, with strategy 1 as a configurable fallback compactor for sessions where the LLM hasn't compressed enough and context still overflows. The key insight: the agent LLM already "knows" what it needs from past results while reasoning about the next step — it is the best possible judge of what can be compressed.

---

## 3. SYSTEM ARCHITECTURE OVERVIEW

```
┌──────────────────────────────────────────────────────────────────────┐
│                          NEXUS FRAMEWORK                             │
│                                                                      │
│  ┌─────────────┐    ┌───────────────┐    ┌──────────────────────┐   │
│  │  AgentConfig │    │  AgentRunner   │    │   SessionManager     │   │
│  │  (Pydantic)  │───▶│ (Orchestrator) │───▶│   (Persistence)      │   │
│  └─────────────┘    └───────────────┘    └──────────────────────┘   │
│         │                   │                        │               │
│         │           ┌───────┴───────┐                │               │
│  ┌──────▼──────┐  ┌─▼──────┐  ┌────▼────┐   ┌───────▼────────────┐ │
│  │ ToolRegistry│  │LLMProxy│  │ Context │   │   StorageAdapter   │ │
│  │ (Plugin Sys)│  │        │  │ Builder │   │ file/sqlite/pg/redis│ │
│  └──────┬──────┘  └────────┘  └────┬────┘   └────────────────────┘ │
│         │                          │                                  │
│  ┌──────▼──────────────────────────▼──────────────────────────────┐ │
│  │                  RCS PIPELINE (when enabled)                    │ │
│  │                                                                  │ │
│  │  1. ContextWindowBuilder tags unsummarized tool results [TCn]   │ │
│  │  2. RCSSystemPromptInjector appends _context_updates docs       │ │
│  │     to system prompt explaining the compression contract        │ │
│  │  3. LLM calls next tool → includes _context_updates in args     │ │
│  │  4. ContextUpdateInterceptor strips _context_updates from args  │ │
│  │     BEFORE tool executes, persists summaries to session         │ │
│  │  5. ContextWindowBuilder: summarized TCs → no tag (plain text)  │ │
│  │                           unsummarized TCs → [TCn] tag          │ │
│  │                                                                  │ │
│  │  FALLBACK (if context still overflows):                         │ │
│  │  6. ServerCompactor: bulk-summarizes oldest tagged TCs          │ │
│  │     via a separate LLM call (configurable, off by default)      │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. MODULE SPECIFICATIONS

### MODULE 1: `nexus.config` — Configuration System

All configuration is **Pydantic v2 models**. Nothing is read from env vars by the framework. All secrets and settings are passed explicitly at construction or call time.

#### 4.1.1 `LLMProviderConfig`

```python
class LLMProviderConfig(BaseModel):
    provider: Literal["openai", "anthropic", "gemini", "ollama", "litellm", "groq",
                      "openrouter", "bedrock", "azure_openai", "custom"]
    model: str                          # e.g. "gpt-4o", "claude-sonnet-4-20250514"
    api_key: SecretStr                  # Never from env; always explicit
    base_url: Optional[str] = None      # For custom/ollama endpoints
    api_version: Optional[str] = None   # Azure needs this
    timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0
    extra_headers: dict[str, str] = {}
    default_params: dict[str, Any] = {} # temperature, top_p, etc.
```

#### 4.1.2 `AgentPersonaConfig`

```python
class AgentPersonaConfig(BaseModel):
    role: str                           # e.g. "Senior Data Analyst"
    goal: str                           # Task-level goal statement
    backstory: Optional[str] = None     # Optional enrichment
    system_prompt: Optional[str] = None # Full override (replaces role/goal/backstory template)
    system_prompt_template: str = DEFAULT_SYSTEM_TEMPLATE  # Jinja2 template
```

#### 4.1.3 `TurnConfig`

```python
class TurnConfig(BaseModel):
    max_turns: int = 10                 # Max agentic loop iterations
    max_tool_calls_per_turn: int = 5    # Guard against tool call storms
    stop_on_empty_tool_calls: bool = True
    stop_sequences: list[str] = []
    stop_on_result_type: bool = True
    human_in_loop_after_turns: Optional[int] = None
    turn_timeout_seconds: int = 300
```

#### 4.1.4 `RuntimeContextSummarizerConfig`

**The primary mechanism is LLM-driven inline compression via `_context_updates`.**  
The server never calls a separate LLM to summarize — the agent does it itself.

```python
class RuntimeContextSummarizerConfig(BaseModel):
    enabled: bool = False

    # ── TC TAGGING ──────────────────────────────────────────────────
    # Format of the tag prepended to unsummarized tool results in context.
    # Must be recognizable to the LLM as "this result is still compressible."
    tc_tag_format: str = "[TC{n}]"      # e.g. [TC1], [TC2] ...
    # Whether to include the tool name + key args in the tag line
    # "[TC1] web_search(query='climate policy')" vs just "[TC1]"
    tc_tag_include_tool_signature: bool = True

    # ── _context_updates INJECTION ───────────────────────────────────
    # When enabled, the framework auto-injects _context_updates as an
    # OPTIONAL parameter into the JSON schema of EVERY registered tool.
    # The LLM reads the injected description and learns the compression contract.
    context_updates_param_name: str = "_context_updates"
    context_updates_param_description: str = DEFAULT_CONTEXT_UPDATES_PARAM_DESC

    # ── SYSTEM PROMPT INJECTION ──────────────────────────────────────
    # When RCS is enabled, this block is appended to the system prompt
    # (after persona content) to explain the TC/context_updates contract.
    # Fully overridable.
    rcs_system_block: str = DEFAULT_RCS_SYSTEM_BLOCK

    # ── COMPRESSION BEHAVIOUR ─────────────────────────────────────────
    # Sentinel the LLM should return in summary when a TC result had
    # nothing useful (so we can visually distinguish "compressed to nothing"
    # from "not yet compressed")
    empty_summary_sentinel: str = "[]"

    # Whether to keep the raw response in storage even after summarization
    # (for audit/debugging). Does not affect context window — only storage.
    keep_raw_response_in_storage: bool = True

    # ── FALLBACK SERVER COMPACTOR ────────────────────────────────────
    # Runs only when context still overflows after LLM-driven compression.
    # Makes a separate LLM call — off by default.
    fallback_compactor: "ServerCompactorConfig" = ServerCompactorConfig()
```

#### 4.1.5 `ServerCompactorConfig`

The server-side fallback. Only activates if `enabled=True` and context token count exceeds `trigger_token_threshold` **after** LLM-driven `_context_updates` have already been processed.

```python
class ServerCompactorConfig(BaseModel):
    enabled: bool = False               # Off by default; LLM-driven RCS is primary

    # Trigger: fire only when context exceeds this many tokens
    trigger_token_threshold: int = 12000

    # The compactor will summarize the oldest N still-tagged (unsummarized) TCs
    compact_oldest_n_tcs: int = 5

    # The LLM prompt used to generate the forced summary
    # Receives: {tc_id}, {tool_name}, {tool_input}, {raw_response}
    compactor_prompt: str = DEFAULT_COMPACTOR_PROMPT

    # LLM to use for compaction (can be cheaper/smaller model)
    # Falls back to agent's main LLM if None
    compactor_llm: Optional["LLMProviderConfig"] = None

    max_compacted_summary_tokens: int = 150
```

#### 4.1.6 `MemoryConfig`

```python
class MemoryConfig(BaseModel):
    short_term_max_messages: int = 50
    entity_memory_enabled: bool = False
    entity_extraction_prompt: str = DEFAULT_ENTITY_EXTRACTION_PROMPT
    vector_memory_enabled: bool = False
    vector_store_config: Optional[dict] = None
    working_memory_enabled: bool = False
    working_memory_max_tokens: int = 1000
```

#### 4.1.7 `AgentConfig` (Top-Level)

```python
class AgentConfig(BaseModel):
    agent_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: Optional[str] = None

    llm: LLMProviderConfig
    persona: AgentPersonaConfig
    turns: TurnConfig = TurnConfig()
    rcs: RuntimeContextSummarizerConfig = RuntimeContextSummarizerConfig()
    memory: MemoryConfig = MemoryConfig()

    tool_plugins: list[str] = []
    sub_agents: list[str] = []
    result_type_schema: Optional[dict] = None

    trace_enabled: bool = True
    trace_sink: Literal["stdout", "otel", "custom", "none"] = "stdout"
    trace_sink_config: dict = {}

    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True
```

---

### MODULE 2: `nexus.session` — Session & Persistence

#### 4.2.1 Session Data Models

```python
class ToolCallRecord(BaseModel):
    tc_id: str                          # e.g. "TC1", "TC7" — globally unique per session
    tc_index: int                       # Integer index (1-based, session-scoped)
    tool_name: str
    tool_plugin: str
    tool_input: dict                    # args WITHOUT _context_updates (stripped before storage)
    raw_response: str                   # Original tool output — always kept
    summarized_response: Optional[str] = None  # Set when LLM submits _context_updates for this TC
    # None  → not yet summarized; show with [TCn] tag in context
    # str   → summarized; show WITHOUT tag as plain context text
    # "[]"  → summarized to nothing (empty sentinel); omit from context entirely
    summarized_by_turn: Optional[int] = None  # Which turn's _context_updates wrote this
    tokens_raw: int
    tokens_summarized: Optional[int] = None
    timestamp: datetime
    is_dropped: bool = False            # True if summary == empty sentinel

class TurnRecord(BaseModel):
    turn_index: int
    user_message: Optional[str]
    llm_messages: list[dict]            # Raw LLM message dicts (role/content/tool_calls)
    tool_calls: list[ToolCallRecord]
    context_updates_received: list[dict] = []   # Raw _context_updates from LLM this turn
    total_tokens_in: int
    total_tokens_out: int
    tokens_saved_this_turn: int = 0    # Tokens removed from context via _context_updates
    duration_ms: int
    timestamp: datetime
    status: Literal["completed", "error", "interrupted", "max_turns_reached"]
    error: Optional[str]

class AgentSession(BaseModel):
    session_id: str
    agent_id: str
    tenant_id: Optional[str]
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    turns: list[TurnRecord] = []
    tc_counter: int = 0                 # Global TC index counter for this session
    entity_memory: dict = {}
    working_memory: str = ""
    metadata: dict = {}
    is_active: bool = True
    total_tokens_saved_by_rcs: int = 0  # Cumulative savings across all turns
```

#### 4.2.2 Storage Adapter Interface

```python
from abc import ABC, abstractmethod

class StorageAdapter(ABC):
    @abstractmethod
    async def save_session(self, session: AgentSession) -> None: ...

    @abstractmethod
    async def load_session(self, session_id: str) -> Optional[AgentSession]: ...

    @abstractmethod
    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> list[AgentSession]: ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> None: ...

    @abstractmethod
    async def append_turn(self, session_id: str, turn: TurnRecord) -> None:
        """Atomic append — avoids full re-serialization for large sessions."""
        ...

    @abstractmethod
    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
    ) -> None:
        """
        Atomic update of a single ToolCallRecord's summarized_response field.
        Called immediately when _context_updates are received, before tool executes.
        """
        ...
```

#### 4.2.3 Built-in Storage Adapters

**`MemoryStorageAdapter`**
```
- Backend: Python dict (in-process)
- Use case: Testing, short-lived tasks, unit tests
- Thread-safety: asyncio.Lock per session_id
- Config params: max_sessions (LRU eviction), ttl_seconds
```

**`FileStorageAdapter`**
```
- Backend: Filesystem JSON files
- Config params:
    base_path: str
    filename_template: str              # Default: "{session_id}.json"
    overwrite_mode: Literal["full_rewrite", "append_jsonl"]
    pretty_print: bool
    compression: Optional[Literal["gzip"]]
- Locking: filelock library
- update_tc_summary: loads file, patches ToolCallRecord, rewrites
```

**`SQLiteStorageAdapter`**
```
- Backend: SQLite via aiosqlite
- Config params:
    db_path: str
    table_prefix: str = "nexus_"
    wal_mode: bool = True
    auto_migrate: bool = True
- Schema:
    nexus_sessions   (session_id PK, agent_id, tenant_id, user_id,
                      created_at, updated_at, tc_counter, metadata JSON,
                      total_tokens_saved, is_active)
    nexus_turns      (turn_id PK, session_id FK, turn_index, data JSON)
    nexus_tool_calls (tc_id PK, session_id FK, turn_index, tool_name,
                      tool_input JSON, raw_response TEXT, summarized_response TEXT,
                      summarized_by_turn INT, tokens_raw INT, tokens_summarized INT,
                      is_dropped BOOL, timestamp)
    nexus_entity_mem (session_id FK, key, value, updated_at)
- update_tc_summary: single UPDATE on nexus_tool_calls where tc_id = ?
```

**`PostgreSQLStorageAdapter`**
```
- Backend: PostgreSQL via asyncpg
- Config params:
    dsn: SecretStr
    pool_size: int = 10
    max_overflow: int = 20
    schema: str = "public"
    table_prefix: str = "nexus_"
    auto_migrate: bool = True
- Features:
    - Row-level locking for concurrent turn appends
    - JSONB columns with GIN indexes
    - Tenant isolation via RLS policies (optional)
    - update_tc_summary: single atomic UPDATE, no lock contention
```

**`RedisStorageAdapter`**
```
- Backend: Redis via redis-py async
- Config params:
    url: SecretStr
    key_prefix: str = "nexus:"
    session_ttl_seconds: int = 86400
    serialization: Literal["json", "msgpack"] = "json"
- Storage pattern:
    nexus:{session_id}:meta      → session metadata hash
    nexus:{session_id}:turns     → list of turn JSON strings
    nexus:{session_id}:tcs       → hash: tc_id → ToolCallRecord JSON
    nexus:{session_id}:entity    → hash of entity memory
- update_tc_summary: HSET on tcs hash — O(1) atomic
```

#### 4.2.4 `SessionStorageConfig`

```python
class SessionStorageConfig(BaseModel):
    adapter: Literal["memory", "file", "sqlite", "postgresql", "redis", "custom"]
    adapter_config: dict = {}
    custom_adapter_class: Optional[str] = None
    auto_save_after_each_turn: bool = True
    save_on_error: bool = True
```

#### 4.2.5 `SessionMigrator`

```python
class SessionMigrator:
    """
    Migrates sessions between storage adapters.
    Use case: file → sqlite for dev-to-staging, sqlite → postgres for scale-up.
    """
    async def migrate(
        self,
        source: StorageAdapter,
        target: StorageAdapter,
        tenant_id: Optional[str] = None,   # None = migrate all
        session_ids: Optional[list[str]] = None,  # None = migrate all
        batch_size: int = 100,
        on_progress: Optional[Callable] = None,
    ) -> MigrationResult: ...

class MigrationResult(BaseModel):
    sessions_migrated: int
    sessions_failed: int
    errors: list[str]
    duration_ms: int
```

---

### MODULE 3: `nexus.tools` — Tool & Plugin System

#### 4.3.1 Tool Definition

```python
class ToolDefinition(BaseModel):
    name: str
    description: str
    plugin: str
    parameters_schema: dict             # JSON Schema — _context_updates injected here by RCS
    response_schema: Optional[dict] = None
    timeout_seconds: int = 30
    requires_approval: bool = False
    retry_on_error: bool = True
    max_retries: int = 2
    is_async: bool = True
    tags: list[str] = []
    metadata: dict = {}
    # NOTE: No per-tool rewriter config. Compression is done by the LLM
    # via _context_updates. The framework does not rewrite responses server-side
    # (except via the opt-in ServerCompactor fallback).
```

#### 4.3.2 Tool Registration Decorators

```python
@tool_plugin("web_search")
class WebSearchPlugin:
    def __init__(self, deps: RunContext):
        self.http_client = deps.http_client

    @tool(description="Search the web for current information")
    async def web_search(self, query: str, num_results: int = 5) -> list[dict]:
        ...

    @tool(description="Fetch full content of a URL", tags=["external-api"])
    async def fetch_url(self, url: str) -> str:
        ...
```

Note: When RCS is enabled, the framework automatically adds `_context_updates` to each tool's parameters schema at runtime. Plugin authors do NOT declare it — it is injected by `RCSSchemaInjector`.

#### 4.3.3 `_context_updates` Schema Injection

When `rcs.enabled = True`, the `ToolRegistry` wraps every tool schema with this additional property before sending to the LLM:

```json
{
  "_context_updates": {
    "type": "array",
    "description": "<from rcs.context_updates_param_description>",
    "items": {
      "type": "object",
      "required": ["tc_id", "summary"],
      "properties": {
        "tc_id": {
          "type": "string",
          "description": "The TC tag of the result to compress, e.g. 'TC1', 'TC3'"
        },
        "summary": {
          "type": "string",
          "description": "Your compact summary of that result. Pass '[]' if the result had nothing useful and should be dropped."
        }
      }
    },
    "default": []
  }
}
```

This injection happens in `ToolRegistry.get_tool_schemas_for_llm(rcs_config)` — not in the tool definition itself. The actual tool function never receives `_context_updates`; it is stripped by `ContextUpdateInterceptor` before execution.

#### 4.3.4 `ContextUpdateInterceptor`

```python
class ContextUpdateInterceptor:
    """
    Runs BEFORE a tool is executed.
    1. Extracts _context_updates from tool call arguments.
    2. Removes _context_updates from args dict (tool never sees it).
    3. Persists each summary to session storage via update_tc_summary().
    4. Updates session.total_tokens_saved_by_rcs counter.
    Returns cleaned args dict and list of ContextUpdate records.
    """

    async def intercept(
        self,
        tool_call: ToolCallRequest,
        session: AgentSession,
        current_turn_index: int,
        storage: StorageAdapter,
        rcs_config: RuntimeContextSummarizerConfig,
    ) -> tuple[dict, list[ContextUpdate]]:
        raw_args = tool_call.tool_input
        updates_raw = raw_args.pop(rcs_config.context_updates_param_name, [])

        updates: list[ContextUpdate] = []
        for item in updates_raw:
            tc_id = item.get("tc_id", "").strip()
            summary = item.get("summary", "").strip()
            if not tc_id:
                continue

            update = ContextUpdate(
                tc_id=tc_id,
                summary=summary,
                is_drop=(summary == rcs_config.empty_summary_sentinel or summary == ""),
            )

            # Persist immediately, atomically
            await storage.update_tc_summary(
                session_id=session.session_id,
                tc_id=tc_id,
                summarized_response=summary,
                summarized_by_turn=current_turn_index,
            )

            # Track savings
            original_tc = session.find_tc(tc_id)
            if original_tc:
                saved = original_tc.tokens_raw - len(summary.split())  # approximate
                session.total_tokens_saved_by_rcs += max(0, saved)

            updates.append(update)

        return raw_args, updates


class ContextUpdate(BaseModel):
    tc_id: str
    summary: str
    is_drop: bool
```

#### 4.3.5 `RunContext` — Dependency Injection (SaaS Safe)

```python
class RunContext(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: Optional[str]
    user_id: Optional[str]
    session_id: str
    db: Optional[Any] = None
    http_client: Optional[Any] = None
    cache: Optional[Any] = None
    auth_token: Optional[SecretStr] = None
    extra: dict = {}

    class Config:
        arbitrary_types_allowed = True
```

---

### MODULE 4: `nexus.context` — Context Window Management

#### 4.4.1 `ContextWindowBuilder`

The single source of truth for what the LLM sees each turn. The RCS logic is fully expressed here through how it renders tool call records.

```python
class ContextWindowBuilder:
    """
    Assembles the messages array for each LLM call.

    Tool call rendering rules (when RCS is enabled):
    ─────────────────────────────────────────────────
    CASE 1 — Not yet summarized (summarized_response is None):
        Show with TC tag so LLM knows it can be compressed next turn.

        Format in assistant message or tool result block:
            [TC3] database_query(sql="SELECT count(*) FROM orders")
            <full raw_response content>

    CASE 2 — Summarized (summarized_response is a non-empty string):
        Show WITHOUT TC tag. It is now plain context, not a compression candidate.
        The LLM will not try to summarize it again because there is no TC tag.

        Format:
            database_query result: <summarized_response>

    CASE 3 — Dropped (summarized_response == empty_summary_sentinel "[]"):
        Omit entirely from context. The result had nothing useful.
        Do not show tag, do not show content.

    When RCS is disabled:
        All tool results shown without TC tags — normal content.
    """

    def build(
        self,
        session: AgentSession,
        agent_config: AgentConfig,
        current_user_message: Optional[str],
        token_budget: int,
    ) -> list[dict]:
        """
        Assembly order:
        1. system message (persona + RCS block if enabled)
        2. entity memory block (if enabled)
        3. working memory block (if enabled)
        4. conversation history with TC-rendered tool results
           (oldest turns dropped first to fit budget)
        5. current user message (last)
        """
        ...
```

#### 4.4.2 TC Tag Rendering Detail

The TC tag appears in the **tool result** part of the message history (the `tool` role message after a tool call). Specifically:

```
# In the messages array sent to LLM — unsummarized TC:
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "[TC3] database_query(sql=\"SELECT count(*) FROM orders WHERE status='pending'\")\n\n<full response: 2847 tokens of data...>"
}

# After _context_updates sets summarized_response for TC3:
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "database_query result: 47 pending orders found as of last query"
}
```

The tag is in the `content` field, not a separate message. This means it works with all providers' tool call message formats.

#### 4.4.3 `TokenCounter`

```python
class TokenCounter:
    def count_messages(self, messages: list[dict], model: str) -> int: ...
    def count_string(self, text: str, model: str) -> int: ...
    def estimate_tool_schema_overhead(self, tool_definitions: list[dict]) -> int: ...
```

#### 4.4.4 Group Result Rendering in Context

When a parent agent receives an `AgentGroupResult` from invoking a group, the result is rendered in the context window according to these rules:

**Group Result Rendering Rules:**

```
CASE G1 — AgentGroupResult from group invocation:
    Render as plain text in the assistant message or a dedicated tool result block.
    NO [TCn] tag — group results are black box and already compressed.

    Format in assistant message:
        [AgentGroup: ResearchTeam completed]
        final_response: "Research complete. Found 47 sources, 3 key findings: ..."
        total_turns_used: 12
        total_tokens_saved_by_rcs: 8420

    This appears as a single block — parent LLM cannot see individual member turns.

CASE G2 — Nested group result within parent group result:
    When a group contains nested groups, the parent group's AgentGroupRunner
    includes member_results summaries. These are NOT rendered in the GRANDPARENT's
    context — only the immediate parent sees them (for debugging).

    Example: ResearchTeam's result includes:
        member_results: [
            {"member_name": "WebResearcher", "member_type": "agent", "turns_used": 5, "status": "completed", "summary": "..."},
            {"member_name": "DataAnalysis", "member_type": "group", "turns_used": 4, "status": "completed", "summary": "..."},
        ]
    But the top-level supervisor only sees ResearchTeam's final_response, not these details.
```

**Token Tracking for Groups:**

- `AgentGroupResult.total_tokens_saved_by_rcs` aggregates RCS savings from ALL internal agents across ALL nesting levels
- The parent agent's `ContextWindowBuilder` tracks group-level savings separately via `session.group_token_savings` dict
- When a group completes, its `total_tokens_saved_by_rcs` is added to the parent session's running total
- No double-counting: internal RCS savings are NOT re-counted when the group result is rendered as plain text

**Session Isolation Enforcement:**

- Groups run in isolated sessions — parent session TC counters and group session TC counters never mix
- `ContextUpdateInterceptor` validates that TC IDs in `_context_updates` belong to the CURRENT session only
- Cross-session TC references are rejected with a `RCS_CROSS_SESSION_TC_REFERENCE` event

---

### MODULE 5: `nexus.rcs` — Runtime Context Summarizer

#### 4.5.1 The Full RCS Mechanism (Canonical Reference)

This is the authoritative description of how RCS works end-to-end.

```
──────────────────────────────────────────────────────────────────
SESSION INITIALIZATION (when rcs.enabled = True)
──────────────────────────────────────────────────────────────────
- session.tc_counter starts at 0
- No other special setup needed

──────────────────────────────────────────────────────────────────
TURN N — BUILDING THE PROMPT
──────────────────────────────────────────────────────────────────
ContextWindowBuilder iterates all past ToolCallRecords and renders:

  For each ToolCallRecord in session history:
    if   summarized_response == None           → render with [TCx] tag (full raw_response)
    elif summarized_response == "[]" (dropped) → omit from context entirely
    else summarized_response is a string       → render WITHOUT tag (compact form)

RCSSystemPromptInjector appends DEFAULT_RCS_SYSTEM_BLOCK to system message,
which explains to the LLM:
  - What [TCx] tags mean ("you can compress these when making your next tool call")
  - How to use _context_updates parameter
  - That passing [] means "nothing to compress this time"
  - That it should compress results it no longer needs in full form

ToolRegistry.get_tool_schemas_for_llm() returns all tool schemas WITH _context_updates
injected as an optional array parameter.

──────────────────────────────────────────────────────────────────
TURN N — LLM RESPONSE
──────────────────────────────────────────────────────────────────
LLM reasons about what it has done so far. It sees [TC1], [TC3] still
tagged (large, uncompressed), and [TC2] already in compact form (no tag).

LLM decides to call: search_web(query="...", _context_updates=[
  {"tc_id": "TC1", "summary": "config.yaml: FastAPI app, port 8080, debug=False"},
  {"tc_id": "TC3", "summary": "[]"}   ← TC3 had nothing useful, drop it
])

──────────────────────────────────────────────────────────────────
TURN N — BEFORE TOOL EXECUTION (ContextUpdateInterceptor)
──────────────────────────────────────────────────────────────────
1. Extracts _context_updates from tool args → [{tc_id: TC1, ...}, {tc_id: TC3, ...}]
2. Removes _context_updates from args → search_web only receives {query: "..."}
3. For TC1: calls storage.update_tc_summary("TC1", "config.yaml: FastAPI app...")
4. For TC3: calls storage.update_tc_summary("TC3", "[]") → is_dropped = True
5. Updates session.total_tokens_saved_by_rcs
6. Emits RCS_CONTEXT_UPDATES_APPLIED event

──────────────────────────────────────────────────────────────────
TURN N — TOOL EXECUTION
──────────────────────────────────────────────────────────────────
search_web executes with clean args {query: "..."}.
Result stored as new ToolCallRecord with tc_id = "TC{n+1}", summarized_response = None.
(It starts uncompressed, will get [TCn+1] tag next turn.)

──────────────────────────────────────────────────────────────────
TURN N+1 — BUILDING THE NEXT PROMPT
──────────────────────────────────────────────────────────────────
ContextWindowBuilder renders:
  TC1 → "config.yaml: FastAPI app, port 8080, debug=False"   (compact, no tag)
  TC2 → "[TC2] read_file(path='utils.py')\n<1400 tokens>"    (still uncompressed)
  TC3 → (omitted entirely — dropped)
  TC4 → "[TC4] search_web(query='...')\n<new full result>"   (just created, uncompressed)

Context is now much smaller. LLM has all the important facts from TC1,
nothing from TC3 (rightfully dropped), full TC2 (hasn't compressed it yet),
full TC4 (just created).

On its NEXT tool call, the LLM will see TC2 and TC4 still tagged and may
compress them if it no longer needs them in full.
```

#### 4.5.2 `RCSSystemPromptInjector`

```python
class RCSSystemPromptInjector:
    """
    Appends the RCS contract block to the system message when RCS is enabled.
    Called by ContextWindowBuilder during system message assembly.
    """

    def inject(
        self,
        system_message: str,
        rcs_config: RuntimeContextSummarizerConfig,
    ) -> str:
        """Returns system_message + "\n\n" + rendered RCS block."""
        ...
```

#### 4.5.3 `ServerCompactor` (Fallback)

```python
class ServerCompactor:
    """
    Fallback compactor. Only runs when:
    - config.rcs.fallback_compactor.enabled = True
    - AND token count of current context exceeds trigger_token_threshold
    - AFTER ContextUpdateInterceptor has already processed any LLM-provided
      _context_updates this turn

    Makes a real LLM call (the fallback_compactor.compactor_llm or main LLM).
    Targets the oldest N unsummarized (still-tagged) ToolCallRecords.
    Sets summarized_response on them directly (not via LLM's _context_updates).
    """

    def __init__(
        self,
        config: ServerCompactorConfig,
        llm_proxy: "LLMProxy",
        storage: StorageAdapter,
    ): ...

    async def should_trigger(
        self,
        session: AgentSession,
        current_context_tokens: int,
    ) -> bool: ...

    async def compact(
        self,
        session: AgentSession,
        current_turn_index: int,
    ) -> CompactionResult: ...

class CompactionResult(BaseModel):
    tcs_compacted: list[str]    # TC IDs that were compacted
    tokens_saved: int
    duration_ms: int
```

---

### MODULE 6: `nexus.llm` — LLM Proxy & Adapters

#### 4.6.1 `LLMProxy`

```python
class LLMProxy:
    def __init__(self, config: LLMProviderConfig): ...

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,     # Includes _context_updates schema when RCS on
        result_type: Optional[type[BaseModel]] = None,
        stream: bool = False,
        extra_params: dict = {}
    ) -> LLMResponse: ...

    async def chat_stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
    ) -> AsyncIterator[LLMStreamChunk]: ...

    def count_tokens(self, messages: list[dict]) -> int: ...
```

#### 4.6.2 Provider Adapters

```
nexus/llm/
├── __init__.py
├── base.py              # BaseLLMAdapter ABC
├── adapters/
│   ├── openai.py        # OpenAI + Azure OpenAI
│   ├── anthropic.py     # Anthropic (Claude)
│   ├── gemini.py        # Google Gemini
│   ├── ollama.py        # Ollama local
│   ├── litellm.py       # LiteLLM multi-provider passthrough
│   ├── groq.py
│   └── openrouter.py
└── response.py          # LLMResponse, LLMStreamChunk, ToolCallRequest, TokenUsage
```

```python
class LLMResponse(BaseModel):
    content: Optional[str]
    tool_calls: list[ToolCallRequest] = []
    usage: TokenUsage
    finish_reason: str
    raw_response: dict

class ToolCallRequest(BaseModel):
    id: str
    tool_name: str
    tool_input: dict    # MAY contain _context_updates — interceptor strips it before tool exec

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
```

---

### MODULE 7: `nexus.runner` — Agent Runner (Orchestrator)

#### 4.7.1 `AgentRunner`

```python
class AgentRunner:
    def __init__(
        self,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        storage_config: SessionStorageConfig,
        run_context: RunContext,
    ): ...

    async def run(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        initial_context: Optional[dict] = None,
    ) -> AgentRunResult: ...

    async def run_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentStreamEvent]: ...
```

#### 4.7.2 Agent Loop Pseudocode (with RCS)

```python
async def _run_loop(session, user_message, config, rcs_config):

    storage     = StorageAdapter(config)
    ctx_builder = ContextWindowBuilder(config)
    interceptor = ContextUpdateInterceptor()
    compactor   = ServerCompactor(rcs_config.fallback_compactor, llm_proxy, storage)

    FOR turn_index IN range(config.turns.max_turns):

        # ── 1. BUILD CONTEXT WINDOW ──────────────────────────────────
        # Renders TC tags for unsummarized results, plain text for summarized,
        # omits dropped results, appends RCS system block if enabled.
        messages = ctx_builder.build(
            session=session,
            current_user_message=user_message if turn_index == 0 else None,
            token_budget=config.llm.context_window_tokens,
        )
        current_tokens = token_counter.count_messages(messages)

        # ── 2. FALLBACK COMPACTOR (if needed, before LLM call) ───────
        if rcs_config.fallback_compactor.enabled:
            if await compactor.should_trigger(session, current_tokens):
                await compactor.compact(session, turn_index)
                # Rebuild messages with newly compacted TCs
                messages = ctx_builder.build(session=session, ...)

        # ── 3. CALL LLM ──────────────────────────────────────────────
        # Tool schemas include _context_updates parameter (when RCS on)
        tool_schemas = tool_registry.get_tool_schemas_for_llm(
            plugin_names=config.tool_plugins,
            rcs_config=rcs_config,              # injects _context_updates schema
        )
        llm_response = await llm_proxy.chat(
            messages=messages,
            tools=tool_schemas,
        )

        # ── 4. STOP CONDITIONS ───────────────────────────────────────
        if not llm_response.tool_calls and config.turns.stop_on_empty_tool_calls:
            EMIT AgentStreamEvent(type="final_response", content=llm_response.content)
            BREAK

        # ── 5. PROCESS TOOL CALLS ────────────────────────────────────
        turn_tool_records = []
        all_context_updates = []

        for tool_call_req in llm_response.tool_calls:

            # ── 5a. INTERCEPT _context_updates BEFORE tool runs ──────
            # This is the heart of RCS: LLM's summaries are persisted HERE,
            # BEFORE the tool executes. The tool never sees _context_updates.
            clean_args, updates = await interceptor.intercept(
                tool_call=tool_call_req,
                session=session,
                current_turn_index=turn_index,
                storage=storage,
                rcs_config=rcs_config,
            )
            all_context_updates.extend(updates)

            # ── 5b. ASSIGN TC ID ─────────────────────────────────────
            session.tc_counter += 1
            tc_id = f"TC{session.tc_counter}"

            # ── 5c. EXECUTE TOOL ─────────────────────────────────────
            raw_result = await tool_registry.execute(
                plugin=tool_call_req.tool_name.split(".")[0],
                tool=tool_call_req.tool_name.split(".")[1],
                args=clean_args,               # clean_args = no _context_updates
                run_context=run_context,
            )

            # ── 5d. STORE TOOL CALL RECORD ───────────────────────────
            tc_record = ToolCallRecord(
                tc_id=tc_id,
                tc_index=session.tc_counter,
                tool_name=tool_call_req.tool_name,
                tool_input=clean_args,
                raw_response=str(raw_result),
                summarized_response=None,       # None = not yet summarized
                tokens_raw=token_counter.count_string(str(raw_result)),
            )
            turn_tool_records.append(tc_record)

        # ── 6. CHECK HUMAN-IN-LOOP ───────────────────────────────────
        if config.turns.human_in_loop_after_turns == turn_index:
            YIELD HumanInLoopEvent(...)
            human_input = await WAIT_FOR_HUMAN()

        # ── 7. BUILD AND SAVE TURN RECORD ────────────────────────────
        turn = TurnRecord(
            turn_index=turn_index,
            llm_messages=llm_response.raw_messages,
            tool_calls=turn_tool_records,
            context_updates_received=all_context_updates,
            tokens_saved_this_turn=sum(u.tokens_saved for u in all_context_updates),
            ...
        )
        session.turns.append(turn)
        await storage.append_turn(session.session_id, turn)

        # Prepare tool results for next LLM message
        # (New TC records start untagged in storage; ContextWindowBuilder
        # will render them with [TCn] tag on the NEXT turn automatically)

    RETURN AgentRunResult(
        session_id=session.session_id,
        final_response=llm_response.content,
        turns_used=turn_index + 1,
        total_tokens_saved_by_rcs=session.total_tokens_saved_by_rcs,
        ...
    )
```

#### 4.7.3 `AgentRunResult`

```python
class AgentRunResult(BaseModel):
    session_id: str
    final_response: Optional[str]
    structured_result: Optional[dict]
    turns_used: int
    total_tokens_in: int
    total_tokens_out: int
    total_tokens_saved_by_rcs: int      # Tokens removed from context via _context_updates
    duration_ms: int
    status: Literal["completed", "max_turns_reached", "error", "interrupted"]
    error: Optional[str]
```

---

### MODULE 8: `nexus.multiagent` — Multi-Agent Orchestration

#### 4.8.1 Orchestration Patterns

**Pattern 1: Supervisor (Hierarchical)**
```
SupervisorAgent
├── ResearchAgent (sub-agent)
├── WriterAgent   (sub-agent)
└── ReviewerAgent (sub-agent)

Supervisor calls transfer_to_agent(name="researcher", task="...", context={...})
Sub-agent runs with scoped context (NOT full supervisor session history)
Sub-agent's TC counters are namespaced: "SUB:researcher:TC1"
Sub-agent returns AgentRunResult to supervisor
```

**Pattern 2: Pipeline (Sequential)**
```
Input → AgentA → AgentB → AgentC → Output
```

**Pattern 3: Parallel Fanout**
```
Input → [AgentA, AgentB, AgentC] → Aggregator → Output
```

**Pattern 4: Swarm (Peer-to-Peer Handoffs)**
```
Any agent can hand off to any registered agent.
Handoff carries a context_slice (explicit dict), not full history.
```

#### 4.8.2 `AgentOrchestrator`

```python
class AgentOrchestrator:
    def __init__(
        self,
        agent_configs: dict[str, Union[AgentConfig, "AgentGroupConfig"]],
        tool_registry: ToolRegistry,
        storage_config: SessionStorageConfig,
        orchestration_pattern: Literal["supervisor", "pipeline", "parallel", "swarm"],
        pattern_config: dict = {}
    ): ...

    async def run(
        self,
        user_message: str,
        entry_agent: str,
        run_context: RunContext,
        session_id: Optional[str] = None,
    ) -> OrchestratorResult: ...
```

**Group Support in Orchestrator:**
- All patterns accept `AgentGroupConfig` as member type alongside `AgentConfig`
- Supervisor: `sub_agents` can be `AgentConfig` OR `AgentGroupConfig`
- Pipeline: stages can be `AgentConfig` OR `AgentGroupConfig`
- Parallel: fanout targets can be `AgentConfig` OR `AgentGroupConfig`
- Swarm: registered agents can be `AgentConfig` OR `AgentGroupConfig`
- When a group is invoked, the orchestrator delegates to `AgentGroupRunner` transparently
- The parent agent sees only `AgentGroupResult` — internal group turns are opaque

---

#### 4.8.3 Agent Groups — Composable Black-Box Units

Agent Groups are first-class entities that wrap multiple agents into a single composable unit. Groups can be nested arbitrarily deep — a group can contain other groups, which can contain groups, and so on. Groups are **black box** to their parents: internal agent coordination is completely opaque, only the final `AgentGroupResult` is visible.

**Why Agent Groups?**

Simple sub-agent delegation (supervisor → research_agent) handles basic tasks. But complex tasks require coordinated teams: a research team that internally combines web researchers, data analysts, and fact-checkers working in parallel, supervised by a team lead. Agent Groups provide this compositionality.

**`AgentGroupConfig`**

```python
class AgentGroupConfig(BaseModel):
    group_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: Optional[str] = None

    # Internal orchestration pattern for this group
    pattern: Literal["supervisor", "pipeline", "parallel", "swarm"] = "supervisor"

    # Members: can be AgentConfig or nested AgentGroupConfig (recursive)
    members: list[Union["AgentConfig", "AgentGroupConfig"]] = []

    # Group-level config
    max_turns: int = 20  # Total turns across ALL internal agents (hard cap)
    result_type_schema: Optional[dict] = None  # Same as AgentConfig — forces structured output

    # How to aggregate results from members (for parallel/swarm patterns)
    aggregation_strategy: Literal["concat", "first_complete", "vote", "supervisor"] = "supervisor"

    # Session config (inherited by all members if not overridden)
    session_id_prefix: str = ""

    # Optional: group-level persona that guides internal coordination
    group_persona: Optional[AgentPersonaConfig] = None
```

**`AgentGroupResult`** (new file `nexus/multiagent/results.py`)

```python
class AgentGroupResult(BaseModel):
    """Black-box result from running an agent group. Parent agents see ONLY this."""
    group_id: str
    group_name: str
    final_response: Optional[str]
    structured_result: Optional[dict]
    total_turns_used: int  # Sum of all internal agent turns across all members
    total_tokens_in: int
    total_tokens_out: int
    total_tokens_saved_by_rcs: int  # RCS savings accumulated across all internal agents
    duration_ms: int
    status: Literal["completed", "max_turns_reached", "error", "interrupted"]
    error: Optional[str]
    member_results: list[dict]  # Summary of each member's result (for debugging/audit)
        # Each dict: {member_name, member_type: "agent"|"group", turns_used, status, summary}
```

**`AgentGroupRunner`** (new file `nexus/multiagent/group_runner.py`)

```python
class AgentGroupRunner:
    """Runs an agent group with its internal orchestration pattern.

    Black box to parent: only AgentGroupResult is returned.
    Each member agent runs with its own session and independent TC counters.
    """

    def __init__(
        self,
        group_config: AgentGroupConfig,
        tool_registry: ToolRegistry,
        storage_config: SessionStorageConfig,
        run_context: RunContext,
    ):
        self.group_config = group_config
        self.tool_registry = tool_registry
        self.storage_config = storage_config
        self.run_context = run_context

    async def run(
        self,
        input_message: str,
        session_id: Optional[str] = None,
    ) -> AgentGroupResult:
        """Execute the group with its internal pattern.

        Creates a scoped session for this group. Each member agent
        gets its own sub-session with namespaced TC counters.
        """
        # 1. Create group session (isolated from parent session)
        group_session_id = f"{self.group_config.session_id_prefix}:{self.group_config.group_id}"

        # 2. Dispatch to internal pattern runner
        pattern_runner = self._get_pattern_runner(self.group_config.pattern)

        # 3. Run with scoped context (group session, not parent session)
        result = await pattern_runner.run(
            input_message=input_message,
            members=self.group_config.members,
            session_id=group_session_id,
            run_context=self.run_context,
            max_turns=self.group_config.max_turns,
            tool_registry=self.tool_registry,
            storage_config=self.storage_config,
        )

        # 4. Convert to AgentGroupResult (black box — no internal turn details)
        return self._to_group_result(result)

    def _get_pattern_runner(self, pattern: str):
        """Return the appropriate pattern runner for this group's internal pattern."""
        runners = {
            "supervisor": SupervisorGroupRunner,
            "pipeline": PipelineGroupRunner,
            "parallel": ParallelGroupRunner,
            "swarm": SwarmGroupRunner,
        }
        return runners[pattern](self.group_config, self.tool_registry, self.storage_config, self.run_context)
```

**Internal Pattern Runners (Group-Scoped)**

Each pattern has a group-scoped variant that runs members within the group's session boundary:

- **`SupervisorGroupRunner`**: Runs a supervisor agent that delegates to member agents/groups. The supervisor has access to all member configs. TC counters are namespaced: `GROUP:{group_id}:SUB:{member_name}:TC{n}`.
- **`PipelineGroupRunner`**: Chains members sequentially. Output of member N becomes input of member N+1. Each member runs in its own turn within the group session.
- **`ParallelGroupRunner`**: Fan out to all members in parallel. Waits for all (or uses `aggregation_strategy`). Each member runs with its own session.
- **`SwarmGroupRunner`**: Members can hand off to each other. Handoffs carry context slices, not full history.

**TC Counter Namespacing for Groups**

When a group runs, all TC counters inside are namespaced with the group ID:

```
Format: GROUP:{group_id}:SUB:{member_name}:TC{n}

Example:
  GROUP:a1b2c3d4:SUB:researcher:TC1   ← Researcher agent inside group a1b2c3d4
  GROUP:a1b2c3d4:SUB:data_analysis:TC1 ← Nested group "data_analysis" inside group a1b2c3d4
  GROUP:e5f6g7h8:SUB:writer:TC1       ← Writer agent inside group e5f6g7h8
```

This ensures:
- TC IDs are globally unique across all nested groups
- No TC reference collisions between sibling groups
- RCS summarization works correctly at every nesting level

**RCS at Group Boundaries**

Groups manage their own context internally. The parent agent sees only the `AgentGroupResult`:

1. **Internal RCS**: Each member agent runs with RCS enabled (or disabled) independently. TC counters are namespaced as shown above.
2. **Group Summary**: When the group completes, its `AgentGroupResult` contains a `final_response` field that serves as the compressed summary of all internal work.
3. **No Cross-Group TC References**: A member agent inside a group CANNOT reference TCs from the parent agent's session, and vice versa. This is enforced by session isolation.
4. **No TC Tags on Group Results**: When a parent agent receives an `AgentGroupResult`, it appears as plain text in the parent's context — no `[TCn]` tags, no internal turn details.
5. **Group-Level Token Savings**: `AgentGroupResult.total_tokens_saved_by_rcs` aggregates RCS savings from all internal agents. The parent can track this separately.

**Group Hierarchy Example**

```
SupervisorAgent (top-level)
├── AgentGroup: ResearchTeam (pattern=supervisor)
│   ├── AgentConfig: WebResearcher
│   ├── AgentConfig: FactChecker
│   └── AgentGroup: DataAnalysis (pattern=parallel)
│       ├── AgentConfig: DataFetcher
│       └── AgentConfig: DataAnalyzer
├── AgentGroup: WritingTeam (pattern=pipeline)
│   ├── AgentConfig: Outliner
│   ├── AgentConfig: DraftWriter
│   └── AgentConfig: Editor
└── AgentConfig: Reviewer
```

In this hierarchy:
- The top-level supervisor calls `ResearchTeam` as if it were a single agent
- Inside `ResearchTeam`, a supervisor agent delegates to `WebResearcher`, `FactChecker`, and the nested `DataAnalysis` group
- Inside `DataAnalysis`, two agents run in parallel
- The top-level supervisor never sees individual turns from any group — only `AgentGroupResult` for each group invocation

**Mermaid: Group Hierarchy**

```mermaid
flowchart TD
    A[SupervisorAgent]
    A -->|calls| B[AgentGroup: ResearchTeam]
    A -->|calls| C[AgentGroup: WritingTeam]
    A -->|calls| D[ReviewerAgent]

    B -->|supervisor delegates to|
    B1[WebResearcher]
    B2[FactChecker]
    B3[AgentGroup: DataAnalysis]

    B3 -->|parallel fanout|
    B3a[DataFetcher]
    B3b[DataAnalyzer]

    C -->|pipeline stages|
    C1[Outliner]
    C2[DraftWriter]
    C3[Editor]

    style A fill:#e1f5fe
    style B fill:#f3e5f5
    style C fill:#f3e5f5
    style B3 fill:#e8f5e9
```

**Example Usage**

```python
# Define nested groups
research_group = AgentGroupConfig(
    name="ResearchTeam",
    pattern="supervisor",
    group_persona=AgentPersonaConfig(
        role="research_team_lead",
        goal="Coordinate research activities across web search, data analysis, and fact-checking",
    ),
    members=[
        AgentConfig(name="web_researcher", ...),
        AgentConfig(name="fact_checker", ...),
        AgentGroupConfig(
            name="DataAnalysis",
            pattern="parallel",
            members=[
                AgentConfig(name="data_fetcher", ...),
                AgentConfig(name="data_analyzer", ...),
            ]
        )
    ]
)

writing_group = AgentGroupConfig(
    name="WritingTeam",
    pattern="pipeline",
    members=[
        AgentConfig(name="outliner", ...),
        AgentConfig(name="draft_writer", ...),
        AgentConfig(name="editor", ...),
    ]
)

# Use groups as drop-in replacements for agents in orchestrator
orchestrator = AgentOrchestrator(
    agent_configs={
        "supervisor": supervisor_config,
        "reviewer": reviewer_config,
    },
    group_configs={
        "ResearchTeam": research_group,
        "WritingTeam": writing_group,
    },
    tool_registry=registry,
    storage_config=storage_config,
    orchestration_pattern="supervisor",
    pattern_config={
        "sub_agents": ["ResearchTeam", "WritingTeam", "reviewer"],
        # Note: "ResearchTeam" and "WritingTeam" reference group_configs, not agent_configs
    }
)

result = await orchestrator.run("Research and write a report on AI agents", "supervisor", run_context)

# Parent only sees AgentGroupResult — no internal turns
for group_name, group_result in result.group_results.items():
    print(f"{group_name}: {group_result.total_turns_used} turns, "
          f"{group_result.total_tokens_saved_by_rcs} tokens saved by RCS")
```

**Group Configuration in `AgentConfig`**

Groups are referenced by the parent orchestrator via a new `group_configs` field. Individual agents can also declare group membership:

```python
class AgentConfig(BaseModel):
    # ...existing fields...

    # References to group configs this agent belongs to (for context inheritance)
    group_memberships: list[str] = []  # group_ids this agent is part of

    # If True, this agent can delegate to any group in group_configs
    can_delegate_to_groups: bool = False
```

---

### MODULE 9: `nexus.events` — Observability & Event System

#### 4.9.1 Event Types

```python
class NexusEventType(str, Enum):
    TURN_START = "turn.start"
    TURN_END = "turn.end"
    TURN_ERROR = "turn.error"
    LLM_CALL_START = "llm.call.start"
    LLM_CALL_END = "llm.call.end"
    LLM_STREAM_CHUNK = "llm.stream.chunk"
    TOOL_CALL_START = "tool.call.start"
    TOOL_CALL_END = "tool.call.end"
    TOOL_CALL_ERROR = "tool.call.error"
    TOOL_APPROVAL_REQUIRED = "tool.approval_required"

    # RCS events — all the important ones
    RCS_CONTEXT_UPDATES_RECEIVED = "rcs.context_updates.received"   # LLM sent _context_updates
    RCS_TC_SUMMARIZED = "rcs.tc.summarized"                         # one TC was summarized
    RCS_TC_DROPPED = "rcs.tc.dropped"                               # one TC dropped ([] sentinel)
    RCS_TOKENS_SAVED = "rcs.tokens_saved"                           # cumulative savings update
    RCS_COMPACTOR_TRIGGERED = "rcs.compactor.triggered"             # fallback compactor ran
    RCS_COMPACTOR_COMPLETED = "rcs.compactor.completed"

    SESSION_CREATED = "session.created"
    SESSION_LOADED = "session.loaded"
    SESSION_SAVED = "session.saved"
    AGENT_HANDOFF = "agent.handoff"
    AGENT_COMPLETED = "agent.completed"
    HUMAN_IN_LOOP_PAUSE = "human_in_loop.pause"
    HUMAN_IN_LOOP_RESUME = "human_in_loop.resume"

    # Group events
    GROUP_START = "group.start"                   # Group execution began
    GROUP_END = "group.end"                       # Group completed successfully
    GROUP_ERROR = "group.error"                   # Group failed
    GROUP_TURN_START = "group.turn.start"         # Internal turn within a group
    GROUP_TURN_END = "group.turn.end"             # Internal turn completed
    GROUP_MAX_TURNS_REACHED = "group.max_turns_reached"


class NexusEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: NexusEventType
    timestamp: datetime
    session_id: str
    turn_index: int
    agent_id: str
    tenant_id: Optional[str]
    data: dict
    duration_ms: Optional[int]
```

#### 4.9.2 Event Sinks

```python
class EventSink(ABC):
    @abstractmethod
    async def emit(self, event: NexusEvent) -> None: ...

class StdoutEventSink(EventSink): ...
class OTelEventSink(EventSink): ...
class WebhookEventSink(EventSink): ...
class CustomCallbackSink(EventSink):
    def __init__(self, callback: Callable[[NexusEvent], Awaitable[None]]): ...
```

---

### MODULE 10: `nexus.guardrails` — Input/Output Safety

```python
class GuardrailConfig(BaseModel):
    input_guardrails: list[GuardrailDefinition] = []
    output_guardrails: list[GuardrailDefinition] = []
    on_violation: Literal["block", "warn", "rewrite"] = "block"
    violation_response: str = "I cannot process that request."

class GuardrailDefinition(BaseModel):
    name: str
    type: Literal["keyword_filter", "regex_filter", "llm_classifier", "pii_detector", "custom"]
    config: dict
```

---

### MODULE 11: `nexus.fastapi` — SaaS Integration Layer

```python
# Full per-request isolation. No env vars. No shared state.

@router.post("/chat")
async def chat(
    body: ChatRequest,
    ctx: NexusRequestContext = Depends(get_nexus_context),
):
    runner = AgentRunner(
        config=ctx.agent_config,        # per-request config
        tool_registry=ctx.tool_registry,
        storage_config=ctx.storage_config,
        run_context=ctx.run_context,    # per-request deps (db, user, tenant)
    )
    result = await runner.run(
        user_message=body.message,
        session_id=body.session_id,
    )
    return ChatResponse(
        session_id=result.session_id,
        response=result.final_response,
        turns_used=result.turns_used,
        tokens_saved_by_rcs=result.total_tokens_saved_by_rcs,
    )
```

---

## 5. DEFAULT PROMPTS

### 5.1 `DEFAULT_CONTEXT_UPDATES_PARAM_DESC`
*(Injected into every tool's _context_updates parameter description)*

```
(Optional) Compress previous tool results you no longer need in full.

In this conversation, tool results tagged [TC1], [TC2], etc. are stored in full.
If you are about to make a new tool call and some of those results are no longer
needed verbatim, you can compress them here to save context space.

For each TC you want to compress:
  - "tc_id": The tag, e.g. "TC1"
  - "summary": Your compact 1-3 sentence summary of what was important in it.
               Pass "[]" if the result had nothing useful and can be dropped entirely.

Rules:
  - Only compress TCs you have already used or that are clearly irrelevant.
  - Do NOT compress TCs you might still need in full detail.
  - Pass [] (empty array) if there is nothing to compress right now.
  - Each summary should be self-contained — future turns will only see your summary,
    not the original content.
```

### 5.2 `DEFAULT_RCS_SYSTEM_BLOCK`
*(Appended to system prompt when RCS is enabled)*

```
## Context Management Protocol

This conversation uses a context management system to keep your working memory efficient.

**How it works:**
- Tool results you have received are tagged [TC1], [TC2], etc. in your context.
- These tags mean the full result is still present and available for compression.
- When making any tool call, you may include a `_context_updates` list to compress
  or drop old TC results you have already processed.

**When to compress:**
- You have extracted the key facts from a large result and no longer need it verbatim.
- A result was a dead end (nothing useful) — compress it to [].
- A result was a large file/page you have finished analyzing.

**When NOT to compress:**
- You may need the exact content again later.
- The result contains data you will reference repeatedly (e.g. a schema, a config file
  you are actively editing).

**If you have nothing to compress:** pass `_context_updates: []` — do not omit the field.
This confirms you reviewed past results and chose to keep them. (You may also simply
omit the field entirely if your tool schema makes it optional — both are valid.)

Results without a [TCn] tag are already compressed and cannot be re-summarized.
```

### 5.3 `DEFAULT_COMPACTOR_PROMPT`
*(Used by ServerCompactor fallback only)*

```
A tool call was made during an AI agent run and returned the result below.
The agent has not yet compressed this result and the context window is at risk of overflowing.

Your job: Write a 1-3 sentence factual summary of the most important information
in the result. Focus on facts that an agent would need to reference later.
If the result contains nothing useful (errors, empty responses, irrelevant data),
output exactly: []

Tool: {tool_name}
Input: {tool_input}
Result:
---
{raw_response}
---

Compact summary (or []):
```

### 5.4 `DEFAULT_SYSTEM_TEMPLATE`
*(Jinja2 — rendered before RCS block is appended)*

```jinja2
You are {{ persona.role }}.

Goal: {{ persona.goal }}

{% if persona.backstory %}
Background: {{ persona.backstory }}
{% endif %}

{% if working_memory %}
## Your Working Notes
{{ working_memory }}
{% endif %}

{% if entity_memory %}
## Known Facts
{% for key, value in entity_memory.items() %}
- {{ key }}: {{ value }}
{% endfor %}
{% endif %}

Today's date: {{ current_date }}
```

---

## 6. DIRECTORY STRUCTURE

```
nexus/
├── __init__.py

├── config/
│   ├── __init__.py
│   ├── llm.py                     # LLMProviderConfig
│   ├── agent.py                   # AgentConfig, TurnConfig
│   ├── rcs.py                     # RuntimeContextSummarizerConfig, ServerCompactorConfig
│   ├── memory.py                  # MemoryConfig
│   ├── storage.py                 # SessionStorageConfig
│   └── defaults.py                # All DEFAULT_* prompt constants

├── session/
│   ├── __init__.py
│   ├── models.py                  # AgentSession, TurnRecord, ToolCallRecord, ContextUpdate
│   ├── manager.py                 # SessionManager
│   ├── migrator.py                # SessionMigrator, MigrationResult
│   └── adapters/
│       ├── __init__.py
│       ├── base.py                # StorageAdapter ABC (includes update_tc_summary)
│       ├── memory.py
│       ├── file.py
│       ├── sqlite.py
│       ├── postgresql.py
│       └── redis.py

├── tools/
│   ├── __init__.py
│   ├── registry.py                # ToolRegistry (get_tool_schemas_for_llm with RCS injection)
│   ├── schema_injector.py         # RCSSchemaInjector (_context_updates param injection)
│   ├── interceptor.py             # ContextUpdateInterceptor (strips + persists _context_updates)
│   ├── decorators.py              # @tool_plugin, @tool decorators
│   ├── context.py                 # RunContext
│   └── builtin/
│       ├── working_memory.py
│       ├── handoff.py
│       └── human_in_loop.py

├── llm/
│   ├── __init__.py
│   ├── proxy.py                   # LLMProxy
│   ├── response.py                # LLMResponse, ToolCallRequest, TokenUsage
│   ├── token_counter.py           # TokenCounter
│   └── adapters/
│       ├── base.py
│       ├── openai.py
│       ├── anthropic.py
│       ├── gemini.py
│       ├── ollama.py
│       ├── litellm.py
│       ├── groq.py
│       └── openrouter.py

├── context/
│   ├── __init__.py
│   ├── builder.py                 # ContextWindowBuilder (TC tag rendering logic lives here)
│   └── rcs_injector.py            # RCSSystemPromptInjector

├── rcs/
│   ├── __init__.py
│   └── compactor.py               # ServerCompactor (fallback only)

├── runner/
│   ├── __init__.py
│   ├── agent_runner.py            # AgentRunner (loop with interceptor integration)
│   └── result.py                  # AgentRunResult, AgentStreamEvent

├── multiagent/
│   ├── __init__.py
│   ├── orchestrator.py
│   ├── patterns/
│   │   ├── supervisor.py
│   │   ├── pipeline.py
│   │   ├── parallel.py
│   │   └── swarm.py
│   └── handoff.py

├── guardrails/
│   ├── __init__.py
│   ├── config.py
│   └── validators/
│       ├── keyword.py
│       ├── regex.py
│       ├── llm_classifier.py
│       └── pii.py

├── events/
│   ├── __init__.py
│   ├── models.py
│   ├── emitter.py
│   └── sinks/
│       ├── stdout.py
│       ├── otel.py
│       ├── webhook.py
│       └── callback.py

├── fastapi/
│   ├── __init__.py
│   ├── context.py
│   ├── dependencies.py
│   └── streaming.py

└── utils/
    ├── __init__.py
    ├── jinja.py
    ├── retry.py
    └── serialization.py
```

---

## 7. KEY INTERFACES SUMMARY

### 7.1 Minimal SaaS-Ready Usage with RCS

```python
from nexus import AgentConfig, AgentRunner, LLMProviderConfig, RunContext
from nexus.config import RuntimeContextSummarizerConfig, TurnConfig, SessionStorageConfig

config = AgentConfig(
    name="research_agent",
    llm=LLMProviderConfig(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key="sk-ant-...",            # From user's stored key — never env var
    ),
    persona=AgentPersonaConfig(
        role="Research Analyst",
        goal="Answer questions using web search and return structured findings",
    ),
    rcs=RuntimeContextSummarizerConfig(
        enabled=True,
        # LLM will summarize its own tool results inline via _context_updates.
        # No trigger threshold needed — it happens every turn naturally.
        # Fallback compactor off by default.
        fallback_compactor=ServerCompactorConfig(enabled=False),
    ),
    turns=TurnConfig(max_turns=8),
    tool_plugins=["web_search"],
)

runner = AgentRunner(
    config=config,
    tool_registry=tool_registry,
    storage_config=SessionStorageConfig(
        adapter="sqlite",
        adapter_config={"db_path": "/data/sessions.db"},
    ),
    run_context=RunContext(
        tenant_id="tenant_abc",
        user_id="user_123",
        session_id="session_xyz",
    ),
)

result = await runner.run("What is the current state of carbon capture technology?")
print(result.final_response)
print(f"Tokens saved by RCS: {result.total_tokens_saved_by_rcs}")
```

### 7.2 RCS with Fallback Compactor Enabled

```python
rcs=RuntimeContextSummarizerConfig(
    enabled=True,
    fallback_compactor=ServerCompactorConfig(
        enabled=True,
        trigger_token_threshold=10000,   # Fire only if context reaches 10k tokens
        compact_oldest_n_tcs=3,          # Force-compress the 3 oldest uncompressed TCs
        compactor_llm=LLMProviderConfig( # Use cheaper model for forced compression
            provider="openai",
            model="gpt-4o-mini",
            api_key="sk-...",
        ),
    ),
),
```

### 7.3 Custom _context_updates Description

```python
rcs=RuntimeContextSummarizerConfig(
    enabled=True,
    context_updates_param_description=(
        "Compress old tool results by providing TC ID → brief summary pairs. "
        "Use '[]' as summary to drop a result entirely. Pass [] to skip compression."
    ),
    rcs_system_block=MY_CUSTOM_RCS_BLOCK,  # Override the full contract explanation
),
```

---

## 8. IMPLEMENTATION PHASES

### Phase 1 — Core Foundation (MVP)
- `nexus.config` — All config models
- `nexus.llm` — LLMProxy with OpenAI + Anthropic adapters
- `nexus.tools` — ToolRegistry, `@tool` decorator, RunContext
- `nexus.session` — AgentSession, TurnRecord, ToolCallRecord + MemoryStorageAdapter + FileStorageAdapter
- `nexus.context` — ContextWindowBuilder (basic, no RCS)
- `nexus.runner` — AgentRunner (single agent, no RCS)
- Basic tests

### Phase 2 — RCS (Core Differentiator)
- `nexus.tools.schema_injector` — RCSSchemaInjector (`_context_updates` param injection)
- `nexus.tools.interceptor` — ContextUpdateInterceptor (strip + persist before tool exec)
- `nexus.context.rcs_injector` — RCSSystemPromptInjector
- `nexus.context.builder` — TC tag rendering (tagged vs. plain vs. omitted)
- `nexus.session.adapters.sqlite` — SQLiteStorageAdapter incl. `update_tc_summary`
- `nexus.session.migrator` — SessionMigrator
- Token counting (tiktoken integration)
- RCS integration tests: `_context_updates` round-trip, TC tag lifecycle

### Phase 3 — Production Storage & Observability
- PostgreSQLStorageAdapter + RedisStorageAdapter
- `nexus.rcs.compactor` — ServerCompactor fallback
- `nexus.events` — Full event system with OTel support
- `nexus.fastapi` — SaaS integration layer
- Streaming support (SSE + WebSocket)

### Phase 4 — Multi-Agent & Agent Groups

#### Phase 4a: Basic Multi-Agent Patterns
- `nexus.multiagent` — Supervisor + Pipeline patterns
- Handoff tool (built-in)
- AgentOrchestrator (basic, agents-only)

#### Phase 4b: Agent Groups (Composable Units)
- `AgentGroupConfig` — Group configuration model (recursive members)
- `AgentGroupResult` — Black-box result model
- `AgentGroupRunner` — Executes groups with internal pattern dispatch
- Group-scoped pattern runners: `SupervisorGroupRunner`, `PipelineGroupRunner`, `ParallelGroupRunner`, `SwarmGroupRunner`
- TC counter namespacing: `GROUP:{id}:SUB:{member}:TC{n}`
- Group config in `nexus/config/agent.py`
- Group results in `nexus/multiagent/results.py`
- Group runner in `nexus/multiagent/group_runner.py`

#### Phase 4c: Group Integration
- Extend `AgentOrchestrator` to accept `AgentGroupConfig` as member type
- Group support in all patterns (supervisor, pipeline, parallel, swarm)
- Group rendering in `ContextWindowBuilder` (plain text, no TC tags)
- Group-level events: `GROUP_START`, `GROUP_END`, `GROUP_ERROR`, `GROUP_TURN_START`, `GROUP_TURN_END`
- Session isolation enforcement for nested groups
- Group token savings aggregation

### Phase 5 — Advanced Features
- `nexus.guardrails`
- Parallel fanout + Swarm patterns
- Vector memory adapter
- Entity memory extraction
- Human-in-the-loop approvals
- Remaining LLM adapters (Gemini, Ollama, LiteLLM, Groq)
- Pydantic Logfire / custom observability sinks

---

## 9. CONFIGURATION OVERRIDE MATRIX

| Feature | Override Level | Override Mechanism |
|---|---|---|
| System prompt | Agent-level | `persona.system_prompt` (full override) |
| System prompt template | Agent-level | `persona.system_prompt_template` (Jinja2) |
| RCS system block | Agent-level | `rcs.rcs_system_block` |
| `_context_updates` param description | Agent-level | `rcs.context_updates_param_description` |
| TC tag format | Agent-level | `rcs.tc_tag_format` |
| TC tag includes tool signature | Agent-level | `rcs.tc_tag_include_tool_signature` |
| Empty summary sentinel | Agent-level | `rcs.empty_summary_sentinel` |
| Fallback compactor on/off | Agent-level | `rcs.fallback_compactor.enabled` |
| Fallback compactor prompt | Agent-level | `rcs.fallback_compactor.compactor_prompt` |
| Fallback compactor LLM | Agent-level | `rcs.fallback_compactor.compactor_llm` |
| Fallback compactor threshold | Agent-level | `rcs.fallback_compactor.trigger_token_threshold` |
| Storage adapter | Run-level | `SessionStorageConfig.adapter` |
| Turn limits | Agent-level | `turns.max_turns` |
| Event sinks | Agent-level | `trace_sink` + `trace_sink_config` |
| Tool plugins | Agent-level | `tool_plugins: list[str]` |

---

## 10. TESTING STRATEGY

### Unit Tests
- `RCSSchemaInjector` — verify `_context_updates` param appears correctly in every tool schema
- `ContextUpdateInterceptor` — correct extraction, stripping from args, persistence call
- `ContextWindowBuilder` — TC tag on unsummarized, plain text on summarized, omit on dropped
- `RCSSystemPromptInjector` — block appended correctly, custom block respected
- `ServerCompactor` — trigger condition, correct TC selection, storage update
- `SessionMigrator` — file→sqlite, sqlite→postgres round-trips
- All storage adapters: `update_tc_summary` atomicity, CRUD, concurrent access

### Integration Tests
- Full RCS round-trip: tool call → TC tag in next prompt → LLM returns `_context_updates` → interceptor strips → next prompt shows plain text
- Session resume: save after turn 3, reload, verify TC states intact (None/summarized/dropped)
- `empty_summary_sentinel` flow: TC dropped → omitted from context
- Server compactor fallback: context overflow → compactor fires → tokens reduced
- Multi-tenant isolation: two concurrent sessions, TC counters independent

### Performance Tests
- TC compression ratio: tokens_raw vs tokens_summarized across 20-turn session
- Context growth rate: with RCS on vs off (same task)
- Storage adapter throughput: `update_tc_summary` calls/sec under load
- Concurrent session handling: 50 simultaneous runs

---

## 11. SECURITY & MULTI-TENANCY

1. **API Key isolation** — `LLMProviderConfig.api_key` is `SecretStr`; never logged, never serialized to plain JSON, never passed to tool functions
2. **Tenant isolation** — `tenant_id` stamped on every `AgentSession`, `TurnRecord`, and `ToolCallRecord`; PostgreSQL adapter supports Row Level Security policies; no cross-tenant session leakage possible via storage API
3. **`_context_updates` validation** — `ContextUpdateInterceptor` validates every submitted `tc_id` against the current session's known TCs before persisting; unknown TC IDs are silently dropped and a `RCS_INVALID_TC_REFERENCE` event is emitted — prevents prompt injection via crafted TC references
4. **Tool input sanitization** — `_context_updates` summaries are stored as plain strings and never re-executed as instructions or re-injected into the system prompt; they only appear as tool result content in the `tool` role message
5. **Tool sandboxing** — Tools that execute arbitrary code should run in isolated containers or subprocesses; the framework provides a documented extension point (`tool_sandbox_adapter`) but does not enforce sandboxing in core
6. **Prompt injection defense** — The guardrails layer (`nexus.guardrails`) runs on all user inputs before they reach the agent loop; also runs on LLM outputs before returning to the caller
7. **No global mutable state** — `AgentRunner`, `ToolRegistry`, and all storage adapters are safe to instantiate per-request in async multi-worker FastAPI/Uvicorn deployments; the only shared state is the (immutable after startup) `ToolRegistry` plugin class registry
8. **Secret scrubbing in events** — `NexusEvent` serialization automatically redacts any field matching `SecretStr` type or field names in a configurable redact list before emitting to sinks
9. **Rate limiting** — `AgentRunner` respects `LLMProviderConfig.max_retries` and `retry_delay`; callers are responsible for request-level rate limiting (e.g. FastAPI middleware); framework emits `LLM_RATE_LIMITED` events for observability
10. **Session ownership** — Every `StorageAdapter` method accepts `tenant_id` as an implicit filter; a session can only be loaded/updated by the `tenant_id` it was created with

---

## 12. ERROR HANDLING & RESILIENCE

### 12.1 Error Taxonomy

```python
class NexusError(Exception):
    """Base class for all framework errors."""
    session_id: Optional[str]
    turn_index: Optional[int]

class LLMCallError(NexusError):
    """LLM API call failed after retries."""
    provider: str
    status_code: Optional[int]
    raw_error: str

class ToolExecutionError(NexusError):
    """A registered tool raised an exception."""
    tool_name: str
    tool_input: dict
    original_error: str

class ToolTimeoutError(ToolExecutionError):
    """Tool exceeded its timeout_seconds."""
    timeout_seconds: int

class ContextWindowOverflowError(NexusError):
    """Context exceeds token budget even after compaction attempts."""
    current_tokens: int
    budget_tokens: int

class StorageError(NexusError):
    """Storage adapter operation failed."""
    adapter: str
    operation: str  # "load", "save", "update_tc_summary", etc.

class RCSInterceptorError(NexusError):
    """_context_updates processing failed."""
    raw_updates: list

class SessionNotFoundError(NexusError):
    session_id: str
```

### 12.2 Failure Modes and Behaviour

| Failure | Default Behaviour | Configurable? |
|---|---|---|
| LLM call fails after retries | Raise `LLMCallError`, save turn with `status="error"` | `save_on_error: bool` |
| Tool raises exception | Store error string as `raw_response`, continue turn loop | `retry_on_error`, `max_retries` per tool |
| Tool times out | Raise `ToolTimeoutError`, treated same as tool exception | `timeout_seconds` per tool |
| `_context_updates` has unknown TC ID | Log warning event, skip that update, continue | Not configurable (always safe-skip) |
| `_context_updates` has malformed JSON | Log warning event, skip `_context_updates` entirely, continue | Not configurable |
| Context overflows budget | Try `ServerCompactor` if enabled; else raise `ContextWindowOverflowError` | `fallback_compactor.enabled` |
| Storage `update_tc_summary` fails | Log `STORAGE_ERROR` event, continue turn (TC stays uncompressed) | `save_on_error` |
| Session not found on resume | Raise `SessionNotFoundError` (never silently create a new session on resume) | N/A |

### 12.3 Turn-Level Error Recovery

```python
# AgentRunner saves a partial TurnRecord even on error
# so session history is never silently lost

if error during tool execution:
    turn.status = "error"
    turn.error = str(exception)
    await storage.append_turn(session_id, turn)  # save what we have
    EMIT TURN_ERROR event
    RAISE or CONTINUE based on config
```

---

## 13. COMPLETE RCS WORKED EXAMPLE

This section provides a full end-to-end trace of 3 turns showing exactly what is in the context window at each step, and exactly what changes when `_context_updates` is processed.

### Setup
```
Agent: Code Review Assistant
Tools: read_file, run_tests, search_docs
RCS: enabled, tc_tag_format="[TC{n}]", tc_tag_include_tool_signature=True
```

---

### Turn 1

**Context sent to LLM (abbreviated):**
```
[system]
You are a Code Review Assistant.
Goal: Review the submitted Python file for bugs and style issues.

## Context Management Protocol
Tool results tagged [TCn] can be compressed in your next tool call via _context_updates.
...

[user]
Please review main.py
```

**LLM responds:** calls `read_file(path="main.py")`  
`_context_updates: []` ← nothing to compress yet

**ContextUpdateInterceptor:** `_context_updates` is empty → nothing to persist

**Tool executes:** returns 1,847 tokens of Python code

**TurnRecord saved:**
```
tool_calls: [
  ToolCallRecord(
    tc_id="TC1", tc_index=1,
    tool_name="read_file", tool_input={"path": "main.py"},
    raw_response="<1847 tokens of Python code>",
    summarized_response=None,   ← not yet compressed
    tokens_raw=1847
  )
]
```

---

### Turn 2

**Context sent to LLM:**
```
[system] ...same...

[user] Please review main.py

[assistant] <reads file>

[tool: call_001]
[TC1] read_file(path="main.py")
<full 1847 tokens of Python code>    ← TC tag present, full content
```

**LLM responds:** calls `run_tests(test_file="test_main.py", _context_updates=[
  {"tc_id": "TC1", "summary": "main.py: Flask app, 3 routes (/health, /users, /orders), uses SQLAlchemy ORM, missing input validation on /users POST, 247 lines"}
])`

**ContextUpdateInterceptor fires BEFORE `run_tests` executes:**
1. Extracts `_context_updates` → one item: TC1
2. Strips `_context_updates` from args → `run_tests` receives only `{"test_file": "test_main.py"}`
3. Calls `storage.update_tc_summary("TC1", "main.py: Flask app, 3 routes ...")`
4. TC1's `summarized_response` is now set. `tokens_raw=1847`, `tokens_summarized=31`
5. `session.total_tokens_saved_by_rcs += 1816`
6. Emits `RCS_TC_SUMMARIZED` event

**Tool executes:** `run_tests(test_file="test_main.py")` → returns 623 tokens of test output

**TurnRecord saved with:**
```
context_updates_received: [{"tc_id": "TC1", "summary": "main.py: Flask app, ..."}]
tokens_saved_this_turn: 1816
tool_calls: [
  ToolCallRecord(
    tc_id="TC2", tc_index=2,
    tool_name="run_tests", tool_input={"test_file": "test_main.py"},
    raw_response="<623 tokens of test results>",
    summarized_response=None,   ← not yet compressed
    tokens_raw=623
  )
]
```

---

### Turn 3

**Context sent to LLM — now much smaller:**
```
[system] ...same...

[user] Please review main.py

[assistant] <reads file>

[tool: call_001]
read_file result: main.py: Flask app, 3 routes (/health, /users, /orders), uses
SQLAlchemy ORM, missing input validation on /users POST, 247 lines
                                ↑ NO [TC1] tag — already compressed, plain text
                                ↑ only 31 tokens instead of 1847

[assistant] <runs tests>

[tool: call_002]
[TC2] run_tests(test_file="test_main.py")
<full 623 tokens of test results>    ← TC2 still tagged, not yet compressed
```

**Token savings so far: 1,816 tokens removed from context**

**LLM responds:** calls `search_docs(query="Flask input validation best practices", _context_updates=[
  {"tc_id": "TC2", "summary": "Tests: 12 passed, 2 failed — test_users_post_validation (missing validation) and test_orders_auth (missing auth check)"}
])`

**ContextUpdateInterceptor:**  
TC2 compressed to 23 tokens. Additional savings: 600 tokens.

**Cumulative tokens saved: 2,416** across 3 turns on what would have been a 2,470-token context — **98% compression of historical tool results**.

---

### Summary of TC State After Turn 3

| TC ID | Tool | Raw Tokens | Status | Summarized Tokens | In Context? |
|---|---|---|---|---|---|
| TC1 | read_file | 1,847 | Summarized | 31 | Yes (plain text, no tag) |
| TC2 | run_tests | 623 | Summarized | 23 | Yes (plain text, no tag) |
| TC3 | search_docs | TBD | Unsummarized | — | Yes ([TC3] tagged, full) |

---

## 14. DEPENDENCY MANIFEST

### Core (always required)
```toml
[dependencies]
pydantic = ">=2.0"
pydantic-settings = ">=2.0"
httpx = ">=0.27"           # Async HTTP for LLM API calls
tiktoken = ">=0.7"         # Token counting (OpenAI-compatible)
jinja2 = ">=3.1"           # System prompt templating
anyio = ">=4.0"            # Async primitives
tenacity = ">=8.0"         # Retry logic
```

### Storage adapters (optional, installed per adapter)
```toml
[dependencies.optional]
aiosqlite = ">=0.20"       # SQLiteStorageAdapter
asyncpg = ">=0.29"         # PostgreSQLStorageAdapter
redis = {version=">=5.0", extras=["hiredis"]}  # RedisStorageAdapter
filelock = ">=3.13"        # FileStorageAdapter concurrent locking
alembic = ">=1.13"         # Schema migrations for SQL adapters
```

### LLM provider clients (optional, one or more)
```toml
openai = ">=1.30"          # OpenAI + Azure OpenAI + OpenRouter
anthropic = ">=0.28"       # Anthropic Claude
google-genai = ">=1.0"     # Gemini
litellm = ">=1.40"         # LiteLLM multi-provider
groq = ">=0.9"             # Groq
ollama = ">=0.2"           # Ollama local
```

### Observability (optional)
```toml
opentelemetry-api = ">=1.24"
opentelemetry-sdk = ">=1.24"
opentelemetry-exporter-otlp = ">=1.24"
logfire = ">=0.46"         # Pydantic Logfire (optional sink)
```

### FastAPI integration (optional)
```toml
fastapi = ">=0.111"
uvicorn = {version=">=0.30", extras=["standard"]}
sse-starlette = ">=2.1"    # Server-sent events for streaming
```

### Dev / test
```toml
[dev-dependencies]
pytest = ">=8.0"
pytest-asyncio = ">=0.23"
pytest-mock = ">=3.14"
respx = ">=0.21"           # Mock httpx for LLM adapter tests
faker = ">=25.0"
coverage = ">=7.0"
ruff = ">=0.4"
mypy = ">=1.10"
```

### Install extras
```bash
pip install nexus-agent                          # core only
pip install nexus-agent[sqlite]                  # + SQLite adapter
pip install nexus-agent[postgres]                # + PostgreSQL adapter
pip install nexus-agent[redis]                   # + Redis adapter
pip install nexus-agent[openai]                  # + OpenAI client
pip install nexus-agent[anthropic]               # + Anthropic client
pip install nexus-agent[fastapi]                 # + FastAPI helpers
pip install nexus-agent[all]                     # everything
```

---

## 15. GLOSSARY

| Term | Definition |
|---|---|
| **TC** | Tool Call — a single invocation of a registered tool during an agent run. Numbered per-session as TC1, TC2, etc. |
| **TC tag** | The `[TCn]` prefix prepended to a tool result in the context window when it has not yet been summarized. Its presence signals to the LLM that this result is eligible for compression. |
| **Summarized TC** | A TC whose `summarized_response` has been set (via `_context_updates`). Rendered in context as plain text without TC tag. Cannot be re-summarized. |
| **Dropped TC** | A TC whose `summarized_response` equals the `empty_summary_sentinel` (`"[]"`). Omitted from context entirely. |
| **`_context_updates`** | An array parameter automatically injected into every tool's schema when RCS is enabled. The LLM populates it in its next tool call to compress previous TC results. |
| **ContextUpdateInterceptor** | Framework component that runs before every tool execution: extracts `_context_updates` from args, persists the summaries to storage, then passes clean args to the tool function. |
| **RCS** | Runtime Context Summarization — the system by which the LLM compresses its own tool results inline, with zero extra LLM calls. |
| **ServerCompactor** | Optional fallback component. Makes a real LLM call to force-summarize the oldest uncompressed TCs when context exceeds a token threshold. Off by default. |
| **TC counter** | Per-session incrementing integer stored on `AgentSession.tc_counter`. Never resets within a session. Ensures globally unique TC IDs across all turns. |
| **RunContext** | Per-request dependency container injected into all tool functions. Contains `tenant_id`, `user_id`, `db`, `http_client`, etc. Never global state. |
| **Turn** | One iteration of the agent loop: build context → call LLM → execute tools → intercept `_context_updates` → save TurnRecord. |
| **StorageAdapter** | Abstract interface for session persistence. Implementations: Memory, File, SQLite, PostgreSQL, Redis. The critical method is `update_tc_summary()` for atomic TC compression. |

---

*End of PRD v2.0 — Feed this document section by section to an LLM (starting with Section 4, then 5, then 7) to generate complete module implementations in order of phases listed in Section 8.*
