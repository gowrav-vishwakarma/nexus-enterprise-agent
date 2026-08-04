"""Replay buffer for dropped streams."""

from __future__ import annotations

import asyncio

import pytest

from nexus.serve.replay import StreamReplayBuffer, buffered_stream


class _Event:
    """Stand-in for AgentStreamEvent with the fields the buffer reads."""

    def __init__(self, seq: int, content: str) -> None:
        self.seq = seq
        self.content = content

    def model_dump(self, mode: str = "python") -> dict:
        return {"event_type": "content", "content": self.content, "data": {"seq": self.seq}}


async def _events(count: int):
    for i in range(1, count + 1):
        yield _Event(i, f"chunk-{i}")


@pytest.mark.asyncio
async def test_replay_returns_only_events_after_the_cursor():
    buffer = StreamReplayBuffer()
    async for _ in buffered_stream(_events(5), buffer, "k"):
        pass

    replayed = [p async for p in buffer.replay("k", after_seq=3)]

    assert [p["content"] for p in replayed] == ["chunk-4", "chunk-5"]


@pytest.mark.asyncio
async def test_replay_from_zero_returns_the_whole_run():
    buffer = StreamReplayBuffer()
    async for _ in buffered_stream(_events(3), buffer, "k"):
        pass

    replayed = [p async for p in buffer.replay("k", after_seq=0)]

    assert len(replayed) == 3


@pytest.mark.asyncio
async def test_reattaching_mid_run_follows_until_the_run_finishes():
    """The client should get the tail of a run that is still producing events."""
    buffer = StreamReplayBuffer()
    released = asyncio.Event()

    async def slow_events():
        yield _Event(1, "chunk-1")
        yield _Event(2, "chunk-2")
        await released.wait()
        yield _Event(3, "chunk-3")

    async def produce():
        async for _ in buffered_stream(slow_events(), buffer, "k"):
            pass

    producer = asyncio.create_task(produce())
    await asyncio.sleep(0.01)

    collected = []

    async def consume():
        async for payload in buffer.replay("k", after_seq=1):
            collected.append(payload["content"])

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert collected == ["chunk-2"]

    released.set()
    await asyncio.gather(producer, consumer)

    assert collected == ["chunk-2", "chunk-3"]


@pytest.mark.asyncio
async def test_buffer_is_bounded_and_reports_what_it_dropped():
    buffer = StreamReplayBuffer(max_events_per_session=3)
    async for _ in buffered_stream(_events(10), buffer, "k"):
        pass

    assert buffer.earliest_seq("k") == 8
    replayed = [p async for p in buffer.replay("k", after_seq=0)]
    assert [p["content"] for p in replayed] == ["chunk-8", "chunk-9", "chunk-10"]


@pytest.mark.asyncio
async def test_unknown_key_raises():
    buffer = StreamReplayBuffer()
    assert not buffer.has("missing")
    with pytest.raises(KeyError):
        async for _ in buffer.replay("missing"):
            pass


@pytest.mark.asyncio
async def test_finished_runs_expire():
    buffer = StreamReplayBuffer(ttl_seconds=0.01)
    async for _ in buffered_stream(_events(2), buffer, "k"):
        pass

    assert buffer.has("k")
    await asyncio.sleep(0.05)
    assert not buffer.has("k")
