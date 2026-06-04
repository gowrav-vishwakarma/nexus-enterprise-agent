# Multi-Tenant SaaS Integration Blueprint
### Nexus Agent Framework Architecture & Plan-Based Gating

This document serves as the implementation guide for developers building high-scale, multi-tenant SaaS applications (like the *Hermes* AI platform) on top of the **Nexus Agent Framework**.

---

## 1. Core Architecture Principles

Unlike traditional agent frameworks that maintain global configurations, state, or registries, Nexus is designed with a **SaaS-First, Context-Isolated Philosophy**:

```
           [ Incoming API Request with X-Tenant-ID Header ]
                                  │
                                  ▼
                    [ Tenant Resolution & Auth ]
                                  │
        ┌─────────────────────────┴─────────────────────────┐
        ▼                                                   ▼
[ Build Agent / Group Configs ]              [ Resolve Storage Configurations ]
  - Gated by plan limits                       - Shared or isolated PG / SQLite
  - Pre-selected LLM configurations            - Schema/DSN defined on-the-fly
        │                                                   │
        └─────────────────────────┬─────────────────────────┘
                                  ▼
                 [ Instantiate AgentRunner / Orchestrator ]
                                  │
                                  ▼
                      [ Execute LLM Turn Loop ]
```

- **Stateless Execution**: The execution instances (`AgentRunner` and `AgentOrchestrator`) are fully instantiated on a per-request basis. All provider credentials, model names, memory thresholds, and storage adapters are passed explicitly as configuration models.
- **Tenant Context Isolation**: A `RunContext` is passed throughout the execution path, holding metadata fields such as `tenant_id` and `session_id`.
- **Dynamic Configuration Factories**: Feature gates and plan configurations map directly to Nexus configuration objects during request processing.

---

## 2. Plan-Based Feature Gating Design

Different tenant plan tiers (e.g., `FREE`, `STARTER`, `PRO`, `ENTERPRISE`) are defined via configuration rules. Plan rules map directly to configuration objects in Nexus:

| Plan Feature | Nexus Configuration Field | Description / Guard |
| :--- | :--- | :--- |
| **Max Agentic Loop Iterations** | `TurnConfig.max_turns` | Prevents runaway agent execution costs. |
| **Tool Call Storm Guards** | `TurnConfig.max_tool_calls_per_turn` | Restricts how many tools can be invoked per step. |
| **RCS Context Compression** | `RuntimeContextSummarizerConfig.enabled` | Offloads context size on higher plans using RCS summarization. |
| **Forced Compactor Fallback** | `ServerCompactorConfig.enabled` | Triggers a cheap compactor LLM to condense context when thresholds are exceeded. |
| **Memory Isolation Types** | `MemoryConfig.entity_memory_enabled` / `vector_memory_enabled` | Toggles semantic memory blocks. |
| **Allowed Tool Packages** | `AgentConfig.tool_plugins` | Filter list defining which tool namespaces are registered. |

---

## 3. Database & Storage Isolation Modes

Nexus offers pluggable session storage adapters configured via `SessionStorageConfig`. In multi-tenant environments, storage routing must adapt to the tenant's data isolation requirements:

### Isolation Mode 1: SHARED_SCHEMA
- **Target Tier**: `FREE`, `STARTER`.
- **Strategy**: Multiple tenants share a single database and schema (e.g., PostgreSQL schema name `tenant_shared` or a shared SQLite database).
- **Nexus Mapping**: Columns like `tenant_id` are automatically populated by the runner using `RunContext.tenant_id`. Every query issued by the storage adapter appends a `WHERE tenant_id = ?` clause to isolate records.

### Isolation Mode 2: DEDICATED_SCHEMA
- **Target Tier**: `PRO`.
- **Strategy**: Tenants share the same database server but have their sessions stored in isolated database schemas (e.g., schema `co_acme_corp`).
- **Nexus Mapping**:
  ```python
  SessionStorageConfig(
      adapter="postgresql",
      adapter_config={
          "dsn": "postgresql://shared-db-server/prod_sessions",
          "schema": "co_acme_corp",
          "table_prefix": "nexus_"
      }
  )
  ```

### Isolation Mode 3: DEDICATED_DB (BYODB)
- **Target Tier**: `ENTERPRISE`.
- **Strategy**: Highest compliance tier where the tenant's session history resides on a separate server or database instance.
- **Nexus Mapping**: The application fetches the encrypted DSN string from the tenant record and maps it to a new storage config:
  ```python
  SessionStorageConfig(
      adapter="postgresql",
      adapter_config={
          "dsn": tenant.custom_db_dsn.get_secret_value(),
          "schema": "public",
          "table_prefix": "nexus_"
      }
  )
  ```

---

## 4. Practical Implementation Guide

To see these multi-tenant SaaS integration design patterns fully implemented in code, refer to the verified FastAPI example:

👉 [hermes_saas_api.py](file:///home/gowrav/Development/agent-framework/examples/hermes_saas_api.py)

### How to Run and Verify:
1. Ensure the required FastAPI and security dependencies are present in your workspace:
   ```bash
   uv pip install fastapi pydantic uvicorn
   ```
2. You can launch the server using `uvicorn`:
   ```bash
   uvicorn examples.hermes_saas_api:app --host 0.0.0.0 --port 8000
   ```
3. Test a plan-restricted tool call (e.g., attempting tools on a `FREE` tier compared to a `PRO` tier) by sending the header:
   - `X-Tenant-ID: free_tenant_1`
   - `X-Tenant-ID: pro_tenant_1`
