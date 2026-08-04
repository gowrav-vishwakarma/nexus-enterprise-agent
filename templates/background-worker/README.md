# Background worker starter

Agents that run on a schedule with nobody waiting on the other end.

```bash
export OPENAI_API_KEY=sk-...

# One tick, then exit — for system cron or a Kubernetes CronJob
uv run python templates/background-worker/main.py --once

# Or stay resident and tick every minute
uv run python templates/background-worker/main.py
```

## What [main.py](main.py) shows

- `build_cron_run_context()` gives each job a tenant-scoped, non-persisted session,
  so unattended runs never pollute a user's chat history.
- `JobScheduler` with an `is_due` callback. Nexus ships no cron parser; install
  `croniter` for real cron expressions, otherwise every enabled job fires on every
  tick.
- A prompt that tells the model nobody is available to clarify — unattended runs
  should not stop to ask questions.

Swap `InMemoryJobStore` for a database-backed store before production; the in-memory
one forgets every job on restart. See [jobs.md](../../docs/reference/jobs.md).
