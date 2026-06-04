# Nexus Agent Framework Integration Walkthrough

This walkthrough details the setup, configuration, and execution patterns for the newly implemented components in the Nexus Agent Framework: the **LiteLLM Provider Adapter** and the **SQLite Storage Adapter**.

---

## 1. LiteLLM Routing Layer

The LiteLLM Adapter (`LiteLLMAdapter`) serves as a unified routing layer. This allows the framework to connect with 100+ LLM backends (OpenAI, Anthropic, Gemini, Groq, Ollama, OpenRouter, Bedrock, etc.) using a single OpenAI-compatible interface.

### Routing Logic
1. **Custom endpoint (`base_url`)**: LiteLLM proxy, LM Studio, or any OpenAI-compatible server uses the native `OpenAIAdapter` (model string sent as-is, including prefixed names like `openai/qwen`).
2. **Direct Native Adapters**: `openai` and `anthropic` without `base_url` bypass LiteLLM for their SDKs.
3. **LiteLLM Catch-All**: Other providers (e.g., `gemini`, `groq`, `ollama`) and prefixed models without `base_url` route through `LiteLLMAdapter`.
4. **Model String Prepending**: Non-native providers auto-prefix the model when needed (e.g., `gemini/gemini-2.0-flash-exp`).

Configure a custom endpoint via `NEXUS_LLM_BASE_URL`, `NEXUS_LLM_API_KEY`, `NEXUS_LLM_MODEL`, and `NEXUS_LLM_PROVIDER` (see `.env.example`).

### Configuration Example
```python
from nexus import AgentConfig, LLMProviderConfig, AgentRunner

# Router configuration for Gemini via LiteLLM
llm_config = LLMProviderConfig(
    provider="gemini",
    model="gemini-2.0-flash-exp",
    api_key="YOUR_GEMINI_API_KEY"
)

agent_config = AgentConfig(
    name="nexus-gemini-agent",
    llm=llm_config
)

runner = AgentRunner(config=agent_config)
```

---

## 2. SQLite Persistent Storage Adapter

The SQLite Adapter (`SQLiteStorageAdapter`) provides robust, zero-dependency persistent storage for single-server SaaS configurations or development.

### Implementation Details
- Uses `aiosqlite` for asynchronous file and database operations.
- Stores full session dictionaries in a single JSON text column (`data`).
- Includes indexed database columns (`session_id`, `agent_id`, `tenant_id`, `user_id`) to support fast query filtering without full JSON deserialization.

### Configuration Example
```python
from nexus.config import SessionStorageConfig
from nexus.session.adapters.sqlite import SQLiteStorageAdapter
from nexus.session.manager import SessionManager

# Initialize SQLite adapter
adapter = SQLiteStorageAdapter(db_path="./my_agent_sessions.db")
session_manager = SessionManager(storage_adapter=adapter)

# Or pass configuration via SessionStorageConfig
storage_config = SessionStorageConfig(
    adapter="sqlite",
    adapter_config={"db_path": "./my_agent_sessions.db"}
)
```

---

## 3. Running Verification Tests

To run the complete suite containing the new tests for `test_sqlite.py` and `test_litellm.py`, run:

```bash
uv pip install aiosqlite litellm
pytest -v
```
