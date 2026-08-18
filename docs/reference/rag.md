# RAG (`nexus[rag]`)

**Who this is for:** Developers who want an agent to search a document collection (retrieval-augmented generation) without baking a vendor into the runner.

## Key terms

- **RAG** — Retrieval-augmented generation: look up passages, then let the LLM answer from them.
- **RAGProvider** — One object the runner talks to (`ingest` + `retrieve`).
- **Collection** — A named bucket of chunks, partitioned by tenant (or company/user) via `scope_key`.
- **Chunker** — Splits raw text into smaller passages before embedding.
- **Hybrid search** — Dense (vector) search plus keyword search, fused with Reciprocal Rank Fusion.
- **Reranker** — Optional second pass that reorders candidate chunks (opt-in; may add latency).

Leave `AgentConfig.rag` as `None` (the default) to keep current behaviour: no `rag.retrieve` tool is registered. Existing apps that never set `rag` need no changes.

## Quick start

```python
from nexus.config.agent import AgentConfig
from nexus.rag.config import RAGConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

config = AgentConfig(
    name="librarian",
    llm=llm,
    rag=RAGConfig(provider="in_memory", retrieval={"k": 3, "hybrid": True}),
)
ctx = RunContext(tenant_id="acme", user_id="u1")
runner = AgentRunner(config=config, tool_registry=ToolRegistry(), run_context=ctx)
await runner.rag_provider.ingest(ctx, ["Photosynthesis converts sunlight into energy."])
result = await runner.run("What is photosynthesis?")
```

The runner registers `rag.retrieve` only when `config.rag` is set.

## RAGConfig

Set on `AgentConfig` as `rag` (optional).

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `provider` | No | `"in_memory"` | `in_memory`, `pgvector`, or `custom_class` |
| `provider_class` | No | `None` | Dotted import path when `provider` is `custom_class` |
| `provider_config` | No | `{}` | Kwargs passed to the provider constructor (for `pgvector`, include `dsn`) |
| `collection` | No | `"default"` | Logical collection name (scoped by tenant at run time) |
| `chunker` | No | see ChunkerConfig | How ingested text is split |
| `retrieval` | No | see RetrievalConfig | How `retrieve()` searches |
| `embeddings_class` | No | hashing embeddings | Dotted path to an `EmbeddingsProtocol` implementation |
| `reranker_class` | No | pass-through | Dotted path to a `Reranker` implementation |
| `scope_level` | No | `"tenant"` | `global`, `tenant`, `company`, or `user` partition |

### ChunkerConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `strategy` | No | `"fixed"` | `fixed`, `recursive`, `semantic`, or `none` |
| `chunk_size` | No | `512` | Target chunk size in characters |
| `overlap` | No | `64` | Character overlap between adjacent chunks |
| `contextual` | No | `False` | Prepend a short document-context string before embedding (opt-in cost) |

`semantic` needs an embeddings model. `contextual` does **not** call an LLM by itself: pass `metadata["context"]` or the first 200 characters of the source. Generating a model-written summary is your job.

### RetrievalConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `k` | No | `5` | Number of chunks to return |
| `hybrid` | No | `False` | Run dense + keyword search and fuse with Reciprocal Rank Fusion |
| `rerank` | No | `False` | Pass fused candidates through a reranker |
| `rerank_top_k` | No | `50` | Candidate count fed to the reranker before cutting to `k` |

Contextual retrieval and reranking can add model calls or API latency. Keep them off until you need them.

## Protocols

```python
from nexus.rag import RAGProvider, VectorStore, EmbeddingsProtocol, Chunker, SparseIndex, Reranker
```

| Protocol | Methods |
|----------|---------|
| `RAGProvider` | `ingest(ctx, documents, collection=None)`, `retrieve(ctx, query, k=5)` |
| `VectorStore` | `upsert(collection, chunks)`, `search(collection, query_embedding, k=5)` |
| `EmbeddingsProtocol` | `embed(texts) -> list[list[float]]` |
| `Chunker` | `chunk(text, metadata=None)` |
| `SparseIndex` | `upsert(collection, chunks)`, `search(collection, query, k=5)` |
| `Reranker` | `rerank(query, chunks, k=5)` |

`ingest` accepts a list of strings or a list of `DocumentChunk`. Nexus does not parse PDFs; that is the caller's job.

If you query a collection with a different embedding size than it was ingested with, the provider raises `ValueError` (dimension mismatch) instead of returning a silent bad score.

## Built-in providers

| Provider | Extra | Notes |
|----------|-------|--------|
| `InMemoryRAGProvider` | none | Default for tests and local runs. Hashing embeddings if you do not pass a model. |
| `PGVectorRAGProvider` | `nexus[postgres]` | Dense vectors in Postgres; keyword search via `tsvector`. Pass `dsn` or a pool. |

Optional rerankers (`CohereReranker`, `BGEReranker`) import their SDKs only when constructed. They are not required dependencies.

## Backward-compatible retrieve tool

These still work:

```python
from nexus.rag import InMemoryVectorStore, create_retrieve_plugin, chunk_text

plugin = create_retrieve_plugin(store, embeddings)
```

`RetrieveToolPlugin(store, embeddings)` wraps the pair in `InMemoryRAGProvider`. Collections still use `scope_key(ctx, TENANT, "rag")` for the default collection so old upserts keep matching.

## Isolation

Collections are keyed with `scope_key(ctx, scope_level, "rag")` (or `rag:{name}` for a named collection). Tenant A cannot retrieve tenant B's chunks. Tests in `tests/test_rag_in_memory.py` cover this.

## Eval fixture

`tests/fixtures/rag_eval.jsonl` is a 50-row synthetic Q&A set used by `tests/test_rag_eval_fixture.py` to check the in-memory provider.

## YAML

```yaml
agents:
  librarian:
    rag:
      provider: in_memory
      collection: handbook
      chunker:
        strategy: recursive
        chunk_size: 256
        overlap: 32
      retrieval:
        k: 3
        hybrid: true
```

Runnable example: [examples/rag_memory_manifest.yaml](../../examples/rag_memory_manifest.yaml) and [examples/orchestration/run_rag_memory.py](../../examples/orchestration/run_rag_memory.py).

## Next steps

- [Memory](memory.md) — user facts across chats (separate from RAG)
- [Scope](scope.md) — how tenant keys are built
- [Agent config](agent-config.md)
