"""In-process and Redis rate limits plus a per-provider concurrency cap."""

from __future__ import annotations

import random
import time

from django.conf import settings
from django.core.cache import cache


class RateLimitExceeded(Exception):
    pass


class ConcurrencyTimeout(Exception):
    pass


def allow(key: str, limit: int, window_seconds: int = 60) -> bool:
    bucket = f"ai-rate:{key}:{int(time.time()) // window_seconds}"
    try:
        if cache.add(bucket, 0, timeout=window_seconds + 1):
            pass
        count = cache.incr(bucket)
    except ValueError:
        cache.set(bucket, 1, timeout=window_seconds + 1)
        count = 1
    return count <= limit


class provider_slot:
    """Bound how many calls to one provider run at once."""

    def __init__(self, provider: str):
        self.provider = provider or "unknown"
        self.key = f"ai-inflight:{self.provider}"
        self.held = False

    def __enter__(self):
        deadline = time.monotonic() + 20
        limit = settings.AI_MAX_CONCURRENCY
        while True:
            try:
                if cache.add(self.key, 0, timeout=120):
                    pass
                current = cache.incr(self.key)
            except ValueError:
                cache.set(self.key, 1, timeout=120)
                current = 1
            if current <= limit:
                self.held = True
                return self
            try:
                cache.decr(self.key)
            except ValueError:
                pass
            if time.monotonic() > deadline:
                raise ConcurrencyTimeout("AI provider concurrency limit was reached. Retry shortly.")
            time.sleep(0.05 + random.random() * 0.15)

    def __exit__(self, exc_type, exc, tb):
        if self.held:
            try:
                cache.decr(self.key)
            except ValueError:
                cache.delete(self.key)
        return False
