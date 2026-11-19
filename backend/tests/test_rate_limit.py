"""SlidingWindowLimiter with a fake clock: exact, fast, no sleeping."""

import pytest

from app.core.rate_limit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(clock: FakeClock) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(limit=3, window_seconds=60, clock=clock)


def test_allows_up_to_the_limit_then_blocks(limiter: SlidingWindowLimiter) -> None:
    assert [limiter.hit("a") for _ in range(3)] == [None, None, None]

    assert limiter.hit("a") == 60  # seconds until the oldest attempt leaves the window


def test_window_slides(limiter: SlidingWindowLimiter, clock: FakeClock) -> None:
    limiter.hit("a")
    clock.now += 30
    limiter.hit("a")
    limiter.hit("a")

    clock.now += 29  # first attempt is 59 s old: still inside
    assert limiter.hit("a") == pytest.approx(1)

    clock.now += 1  # now exactly 60 s old: it has left the window
    assert limiter.hit("a") is None


def test_refused_attempts_do_not_extend_the_block(
    limiter: SlidingWindowLimiter, clock: FakeClock
) -> None:
    for _ in range(3):
        limiter.hit("a")
    for _ in range(10):
        clock.now += 5
        limiter.hit("a")  # refused, not recorded

    clock.now += 10  # 60 s after the first three
    assert limiter.hit("a") is None


def test_keys_are_independent(limiter: SlidingWindowLimiter) -> None:
    for _ in range(3):
        limiter.hit("a")

    assert limiter.hit("b") is None


def test_undo_forgets_the_last_attempt(limiter: SlidingWindowLimiter) -> None:
    for _ in range(3):
        limiter.hit("a")
    limiter.undo("a")

    assert limiter.hit("a") is None
    limiter.undo("never-seen")  # no error


def test_reset_clears_a_key(limiter: SlidingWindowLimiter) -> None:
    for _ in range(3):
        limiter.hit("a")
    limiter.reset("a")

    assert limiter.hit("a") is None


def test_stale_keys_are_swept_to_bound_memory(clock: FakeClock) -> None:
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60, clock=clock, max_keys=2)
    limiter.hit("old-1")
    limiter.hit("old-2")
    clock.now += 61

    limiter.hit("new")

    assert set(limiter._hits) == {"new"}
