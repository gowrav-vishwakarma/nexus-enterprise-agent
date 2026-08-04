"""Background worker starter — run agents on a schedule, no user attached.

Run one tick and exit (useful from system cron or a Kubernetes CronJob):

    uv run python templates/background-worker/main.py --once

Or stay resident and tick every minute:

    uv run python templates/background-worker/main.py

Nexus does not ship a cron parser. Install `croniter` for real cron expressions;
without it every enabled job fires on every tick, which is fine for a smoke test.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timedelta

from nexus.config.agent import AgentConfig, AgentPersonaConfig, TurnConfig
from nexus.config.llm import LLMProviderConfig
from nexus.jobs import (
    InMemoryJobStore,
    JobScheduler,
    ScheduledJob,
    build_cron_run_context,
)
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("worker")

# Each job belongs to a tenant; jobs run without a user request behind them.
BASE_CONTEXT = RunContext(tenant_id=os.getenv("WORKER_TENANT", "acme"), user_id="system")


def make_is_due():
    """Return a due-check backed by croniter when it is installed."""
    try:
        from croniter import croniter
    except ImportError:
        logger.warning("croniter not installed — every enabled job fires on every tick")
        return None

    def is_due(job: ScheduledJob, now: datetime) -> bool:
        # Due if the previous firing falls inside the tick window we just covered.
        window = timedelta(seconds=float(os.getenv("WORKER_INTERVAL", "60")))
        previous = croniter(job.cron, now).get_prev(datetime)
        return now - previous < window

    return is_due


def build_runner() -> AgentRunner:
    config = AgentConfig(
        name="background-worker",
        llm=LLMProviderConfig(
            provider="openai",
            model=os.getenv("AGENT_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
        ),
        persona=AgentPersonaConfig(
            role="an unattended operations assistant",
            goal="Complete the scheduled task and report the result briefly",
            # Nobody is on the other end, so it must not stop to ask.
            backstory="Nobody is available to answer questions. State assumptions and finish.",
        ),
        turns=TurnConfig(max_turns=6),
    )
    return AgentRunner(config=config, tool_registry=ToolRegistry())


async def run_job(job: ScheduledJob) -> None:
    """Execute one scheduled prompt in its own non-persisted session."""
    ctx = build_cron_run_context(BASE_CONTEXT, job)
    runner = build_runner()
    runner.run_context = ctx
    result = await runner.run(job.prompt, session_id=ctx.session_id, stream=False)
    logger.info("job %s finished: %s", job.id, (result.final_response or "")[:200])
    # Deliver result.final_response wherever it belongs: email, Slack, a webhook.


async def main(once: bool) -> None:
    store = InMemoryJobStore()  # Swap for a database-backed store in production.
    scheduler = JobScheduler(store, run_factory=run_job, is_due=make_is_due())

    await scheduler.add_job("0 9 * * *", "Summarise yesterday's support tickets.")
    await scheduler.add_job("*/15 * * * *", "Check for failed payments and report.")

    if once:
        fired = await scheduler.run_due_jobs()
        logger.info("ran %d job(s)", len(fired))
        return

    interval = float(os.getenv("WORKER_INTERVAL", "60"))
    scheduler.start_background(interval_seconds=interval)
    logger.info("worker running, tick every %ss — Ctrl-C to stop", interval)
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        scheduler.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run due jobs once and exit")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY first.")
    asyncio.run(main(args.once))
