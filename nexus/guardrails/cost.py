"""Cost tracking, budgets, and rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel

from nexus.scope import scope_key, ScopeLevel
from nexus.tools.context import RunContext


# USD per 1M tokens (approximate defaults; override via config).
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "default": {"input": 1.0, "output": 3.0},
}


class BudgetConfig(BaseModel):
    max_tokens_per_run: Optional[int] = None
    max_cost_usd_per_run: Optional[float] = None
    max_requests_per_minute: Optional[int] = None


class CostTracker:
    """Track token usage and estimated cost for a run."""

    def __init__(self, model: str, pricing: Optional[dict[str, dict[str, float]]] = None):
        self.model = model
        self.pricing = pricing or DEFAULT_PRICING
        self.tokens_in = 0
        self.tokens_out = 0

    def add_usage(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    def estimated_cost_usd(self) -> float:
        rates = self.pricing.get(self.model) or self.pricing.get("default", {})
        return (
            self.tokens_in * rates.get("input", 1.0) / 1_000_000
            + self.tokens_out * rates.get("output", 3.0) / 1_000_000
        )

    def check_budget(self, config: BudgetConfig) -> Optional[str]:
        if config.max_tokens_per_run is not None:
            total = self.tokens_in + self.tokens_out
            if total > config.max_tokens_per_run:
                return f"Token budget exceeded ({total} > {config.max_tokens_per_run})"
        if config.max_cost_usd_per_run is not None:
            cost = self.estimated_cost_usd()
            if cost > config.max_cost_usd_per_run:
                return f"Cost budget exceeded (${cost:.4f} > ${config.max_cost_usd_per_run})"
        return None


class RateLimiter:
    """Simple in-memory per-scope rate limiter."""

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, ctx: RunContext, *, max_per_minute: int) -> bool:
        key = scope_key(ctx, ScopeLevel.TENANT, "rate")
        now = time.time()
        window = self._windows[key]
        window[:] = [t for t in window if now - t < 60]
        if len(window) >= max_per_minute:
            return False
        window.append(now)
        return True
