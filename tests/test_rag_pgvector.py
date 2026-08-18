"""PGVector RAG provider tests — skip unless NEXUS_TEST_PG_DSN is set."""

import os

import pytest

from nexus.rag.config import RAGConfig, RetrievalConfig
from nexus.rag.embeddings import HashingEmbeddings
from nexus.tools.context import RunContext


@pytest.fixture
async def pg_provider():
    dsn = os.getenv("NEXUS_TEST_PG_DSN")
    if not dsn:
        pytest.skip("NEXUS_TEST_PG_DSN not set")
    pytest.importorskip("asyncpg")
    from nexus.rag.providers.pgvector import PGVectorRAGProvider

    provider = PGVectorRAGProvider(
        dsn=dsn,
        embeddings=HashingEmbeddings(dim=32),
        config=RAGConfig(
            collection="test_pg",
            retrieval=RetrievalConfig(k=3, hybrid=True),
        ),
        table="nexus_rag_chunks_test",
    )
    yield provider
    await provider.close()


@pytest.mark.asyncio
async def test_pgvector_ingest_retrieve(pg_provider):
    ctx = RunContext(tenant_id="pg-t", user_id="u1")
    await pg_provider.ingest(
        ctx,
        ["Penguins live in Antarctica.", "Cacti grow in deserts."],
    )
    hits = await pg_provider.retrieve(ctx, "penguins Antarctica", k=2)
    assert hits
    assert any("Penguin" in h.text for h in hits)


@pytest.mark.asyncio
async def test_pgvector_tenant_isolation(pg_provider):
    a = RunContext(tenant_id="pg-a", user_id="u1")
    b = RunContext(tenant_id="pg-b", user_id="u1")
    await pg_provider.ingest(a, ["Alpha-only pineapple document."])
    await pg_provider.ingest(b, ["Beta-only blueberry document."])
    hits_a = await pg_provider.retrieve(a, "pineapple", k=5)
    assert all("blueberry" not in h.text.lower() for h in hits_a)
