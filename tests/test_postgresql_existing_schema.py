"""PostgreSQL existing-schema mode (no Nexus DDL)."""

import os

import pytest

from nexus.session.adapters.postgresql import PostgreSQLStorageAdapter
from nexus.session.manager import SessionManager


@pytest.mark.asyncio
async def test_existing_schema_custom_table_no_ddl():
    dsn = os.getenv("NEXUS_TEST_PG_DSN")
    if not dsn:
        pytest.skip("NEXUS_TEST_PG_DSN not set")
    asyncpg = pytest.importorskip("asyncpg")

    schema = os.getenv("NEXUS_TEST_PG_SCHEMA", "public")
    table = "custom_agent_sessions"
    qualified = f'"{schema}".{table}' if schema != "public" else table

    conn = await asyncpg.connect(dsn)
    try:
        if schema != "public":
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {qualified} (
                session_id  TEXT PRIMARY KEY,
                agent_id    TEXT NOT NULL,
                tenant_id   TEXT,
                user_id     TEXT,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ NOT NULL,
                updated_at  TIMESTAMPTZ NOT NULL,
                data        JSONB NOT NULL
            )
            """
        )
    finally:
        await conn.close()

    adapter = PostgreSQLStorageAdapter(
        dsn=dsn,
        schema=schema,
        schema_mode="existing",
        sessions_table=table,
        auto_migrate=False,
    )
    manager = SessionManager(storage_adapter=adapter)

    sess = await manager.create_session(
        agent_id="custom-agent",
        session_id="existing-schema-sess",
        tenant_id="t1",
        user_id="u1",
    )
    assert sess.session_id == "existing-schema-sess"

    loaded = await manager.load_session("existing-schema-sess")
    assert loaded is not None
    assert loaded.agent_id == "custom-agent"

    await adapter.close()

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"DROP TABLE IF EXISTS {qualified}")
    finally:
        await conn.close()
