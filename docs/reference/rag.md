# RAG (`nexus[rag]`)

Scope-namespaced retrieval via `rag.retrieve` tool.

```python
from nexus.rag import InMemoryVectorStore, create_retrieve_plugin, chunk_text
from nexus.scope import ScopeLevel, scope_key
```

Collections are keyed with `scope_key(ctx, ScopeLevel.TENANT, "rag")` so tenant data never mixes.

For production, implement `VectorStore` with pgvector (Postgres extra) or your own backend.
