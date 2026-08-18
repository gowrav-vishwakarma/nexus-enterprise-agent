"""Optional Honcho provider — mocked client, skip import of the vendor SDK."""

import pytest

from nexus.memory.providers.honcho import HonchoMemoryProvider
from nexus.tools.context import RunContext


class _FakeHoncho:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.deleted: list[str] = []

    def dialectic(self, query, session_id="", limit=5):
        del query, limit
        return [{"id": "h1", "content": f"note for {session_id}"}]

    def add(self, text, session_id=""):
        del session_id
        self.added.append(text)

    def delete(self, key):
        self.deleted.append(key)


@pytest.mark.asyncio
async def test_honcho_provider_search_write_remove():
    client = _FakeHoncho()
    provider = HonchoMemoryProvider(client=client)
    ctx = RunContext(tenant_id="acme", user_id="u1")
    hits = await provider.search(ctx, "anything", k=3)
    assert "acme:u1" in hits[0]["value"]
    await provider.write(ctx, "role", "cfo")
    assert client.added
    await provider.remove(ctx, "h1")
    assert client.deleted == ["h1"]


def test_honcho_missing_package_raises():
    provider = HonchoMemoryProvider()
    with pytest.raises(ImportError, match="honcho"):
        provider._get_client()
