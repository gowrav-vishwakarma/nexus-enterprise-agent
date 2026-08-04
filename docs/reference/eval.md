# Evaluation harness (`nexus[eval]`)

Deterministic testing without patching `llm_proxy.chat` by hand.

## Mock LLM

```python
from nexus.eval import MockLLMAdapter, MockLLMResponse
from nexus.config.llm import LLMProviderConfig

adapter = MockLLMAdapter(
    LLMProviderConfig(provider="openai", model="gpt-4o"),
    responses=[MockLLMResponse(content="hello")],
)
```

## Dataset eval

```bash
nexus eval tests/fixtures/eval_smoke.json
```

## Session replay

```python
from nexus.eval import SessionReplayer
replayer = SessionReplayer(path)
assert "search" in replayer.tool_names()
```
