"""Optional Mem0 provider — mocked client, skip import of the vendor SDK."""

import pytest

from nexus.memory.providers.mem0 import Mem0MemoryProvider
from nexus.tools.context import RunContext


class _FakeMem0:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.deleted: list[str] = []

    def search(self, query, user_id="", limit=5):
        del query, limit
        return {
            "results": [
                {"id": "m1", "memory": f"fact for {user_id}", "user_id": user_id}
            ]
        }

    def add(self, text, user_id="", metadata=None):
        del user_id, metadata
        self.added.append(text)

    def delete(self, key):
        self.deleted.append(key)


@pytest.mark.asyncio
async def test_mem0_provider_search_write_remove():
    client = _FakeMem0()
    provider = Mem0MemoryProvider(client=client)
    ctx = RunContext(tenant_id="acme", user_id="u1")
    hits = await provider.search(ctx, "anything", k=3)
    assert hits[0]["value"] == "fact for u1"
    await provider.write(ctx, "role", "cfo")
    assert client.added
    await provider.remove(ctx, "m1")
    assert client.deleted == ["m1"]
    facts = await provider.prefetch(ctx)
    assert facts


def test_mem0_missing_package_raises():
    provider = Mem0MemoryProvider()
    with pytest.raises(ImportError, match="mem0"):
        provider._get_client()
