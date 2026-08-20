# Jobs, artifacts, caching, and checkpoints

These four pieces cover work that outlives a single chat turn: scheduled runs,
files, repeated results, and crash recovery. All four are **scope-aware** — they
partition data with the same rules as [scope.md](scope.md), so one tenant can
never read another's jobs, files, or cached answers.

Install the scheduler extra:

```bash
pip install "nexus-enterprise-agent[jobs]"
```

## Scheduled jobs

A **job** is a prompt Nexus runs on a schedule instead of in response to a user
message. `JobScheduler` keeps jobs in a `JobStore` and hands each due job to a
`run_factory` you supply.

Nexus does **not** ship a cron parser. Pass `is_due` to plug in your own
(`croniter`, APScheduler, or a `next_run_at` column). The default fires every
enabled job on every tick, which is only useful in development.

```python
from nexus.jobs import InMemoryJobStore, JobScheduler, build_cron_run_context
from croniter import croniter  # your choice, not a Nexus dependency

store = InMemoryJobStore()

async def run_job(job):
    ctx = build_cron_run_context(base_ctx, job)   # is_cron=True, tenant preserved
    runner = AgentRunner(config=config, tool_registry=registry, run_context=ctx)
    await runner.run(user_message=job.prompt)

scheduler = JobScheduler(
    store,
    run_factory=run_job,
    is_due=lambda job, now: croniter.match(job.cron, now),
)

await scheduler.add_job("0 9 * * *", "Send the daily sales summary", owner="u1")
scheduler.start_background(interval_seconds=60)
```

| Piece | What it does |
|-------|--------------|
| `ScheduledJob` | `id`, `cron`, `prompt`, `enabled`, `metadata` |
| `JobStore` | Protocol: `list_jobs`, `save_job`, `delete_job` |
| `InMemoryJobStore` | Reference store for development; replace it in production |
| `JobScheduler.run_due_jobs()` | Runs every enabled, due job once and returns the jobs it fired |
| `build_cron_run_context()` | Builds a `RunContext` with `is_cron=True` and the tenant carried over |

Disabled jobs (`enabled=False`) are always skipped.

## Artifacts

An **artifact** is a file a run produces or consumes — an upload, an attachment,
a generated report. `LocalArtifactStore` writes them under a user-scoped
directory, so `get()` with another tenant's context returns `None`.

```python
from nexus.artifacts.store import LocalArtifactStore

store = LocalArtifactStore(root="./artifacts")
meta = await store.put(ctx, pdf_bytes, filename="invoice.pdf", content_type="application/pdf")
data = await store.get(ctx, meta.id)
```

Implement the `ArtifactStore` protocol (`put`, `get`) to back this with S3 or
any other object store.

## Caching

`ScopedCache` caches LLM responses or tool results. Keys include the scope, so a
cached answer never crosses tenants. It is **off by default** — construct one and
wire it into your hooks only where repeated identical calls are genuinely safe.

```python
from nexus.cache.scoped import ScopedCache

cache = ScopedCache(ttl_seconds=300)
hit = cache.get(ctx, "llm", payload)
if hit is None:
    hit = await expensive_call()
    cache.set(ctx, "llm", payload, hit)
```

## Run checkpoints

A **checkpoint** is a snapshot of where a run had got to, so a process that
crashes or redeploys mid-run can resume instead of replaying the whole
conversation.

```python
from nexus.runner.checkpoint import checkpoint_from_session

cp = checkpoint_from_session(session, turn_index=3, stream_seq=42)
```

`stream_seq` is the sequence number of the last emitted stream event. Nexus also
stores it on `AgentSession.stream_seq` when the session is saved, so numbering
survives a process restart. A client that reconnects can send the last `seq` it
saw so you skip events it already received — see [streaming.md](streaming.md).
