# Nexus Agent Framework Integration Walkthrough

This walkthrough details the setup, configuration, and execution patterns for the newly implemented components in the Nexus Agent Framework: the **LiteLLM Provider Adapter** and the **SQLite Storage Adapter**.

---

## 1. LiteLLM Routing Layer

The LiteLLM Adapter (`LiteLLMAdapter`) serves as a unified routing layer. This allows the framework to connect with 100+ LLM backends (OpenAI, Anthropic, Gemini, Groq, Ollama, OpenRouter, Bedrock, etc.) using a single OpenAI-compatible interface.

### Routing Logic
1. **Direct Native Adapters**: `openai` and `anthropic` bypass LiteLLM to use their respective optimized libraries (`httpx` for OpenAI and the Anthropic SDK).
2. **LiteLLM Catch-All**: All other provider identifiers (e.g., `gemini`, `groq`, `ollama`, `litellm`, etc.) automatically route through `LiteLLMAdapter`. 
3. **Model String Prepending**: If the model name is not already prefixed with the provider name (e.g., `gemini-2.0-flash-exp`), the adapter prepends the provider name automatically (yielding `gemini/gemini-2.0-flash-exp`).

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
