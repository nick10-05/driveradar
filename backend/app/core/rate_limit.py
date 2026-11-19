"""In-memory sliding-window rate limiter (DESIGN §7.5).

Interview notes:
- Sliding window log: per key, keep the timestamps of recent attempts and drop the ones
  older than the window. "At most N in any W seconds", with no burst at a window edge
  like a fixed per-minute counter allows (N at 0:59 + N at 1:00).
- No Redis (deliberately excluded, DESIGN §0). Known limitation: counters live in one
  process and reset on restart. Fine for one Render instance; with several instances each
  would allow N, and a shared store like Redis would be the fix.
- No locks needed: asyncio runs one coroutine at a time and these methods never await,
  so each call is atomic.
- Callers record an attempt BEFORE the slow work (Argon2), not after. Otherwise 100
  parallel requests could all pass the check while their password checks run.
- time.monotonic, not wall-clock time: it never jumps when the system clock is adjusted.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.max_keys = max_keys  # memory bound: stale keys are swept past this size
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """Record one attempt. Returns None if allowed, else seconds until the next slot.

        A refused attempt is not recorded, so retrying while blocked doesn't extend the block.
        """
        now = self.clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._sweep(now)
            hits = self._hits[key] = deque()
        self._drop_old(hits, now)
        if len(hits) >= self.limit:
            return hits[0] + self.window_seconds - now
        hits.append(now)
        return None

    def undo(self, key: str) -> None:
        """Forget the most recent attempt (it turned out to be a success)."""
        hits = self._hits.get(key)
        if hits:
            hits.pop()

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _drop_old(self, hits: deque[float], now: float) -> None:
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()

    def _sweep(self, now: float) -> None:
        for key in list(self._hits):
            self._drop_old(self._hits[key], now)
            if not self._hits[key]:
                del self._hits[key]


@dataclass(frozen=True)
class AuthLimiters:
    login_email: SlidingWindowLimiter
    login_ip: SlidingWindowLimiter
    register_ip: SlidingWindowLimiter

    @classmethod
    def default(cls, clock: Callable[[], float] = time.monotonic) -> "AuthLimiters":
        fifteen_min, hour = 15 * 60, 60 * 60
        return cls(
            # Primary key: the email can't be faked, unlike the client IP behind proxies.
            login_email=SlidingWindowLimiter(5, fifteen_min, clock),
            # Looser: many students may share one college Wi-Fi IP.
            login_ip=SlidingWindowLimiter(30, fifteen_min, clock),
            # Stops brute-forcing the batch invite code.
            register_ip=SlidingWindowLimiter(10, hour, clock),
        )
