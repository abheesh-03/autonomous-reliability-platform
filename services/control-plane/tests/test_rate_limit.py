"""Phase 16 correction round, item 6: focused, HTTP-free unit tests for
`core/rate_limit.py` itself -- the limiter's own windowing/pruning/
memory-bound behavior, independent of how api/telemetry_auth.py keys
it."""

from control_plane.core.rate_limit import SlidingWindowRateLimiter


def test_limiter_allows_up_to_max_events_then_rejects(monkeypatch):
    limiter = SlidingWindowRateLimiter(max_events=3, window_seconds=60.0)
    assert limiter.check("a") is True
    assert limiter.check("a") is True
    assert limiter.check("a") is True
    assert limiter.check("a") is False


def test_a_rejected_call_does_not_itself_consume_budget(monkeypatch):
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=60.0)
    assert limiter.check("a") is True
    assert limiter.check("a") is False
    assert limiter.check("a") is False  # still false, not further penalized


def test_different_keys_have_independent_budgets():
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=60.0)
    assert limiter.check("a") is True
    assert limiter.check("b") is True
    assert limiter.check("a") is False
    assert limiter.check("b") is False


def test_budget_resets_after_the_window_elapses(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("control_plane.core.rate_limit.time.monotonic", lambda: clock["t"])
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=10.0)
    assert limiter.check("a") is True
    assert limiter.check("a") is False
    clock["t"] += 11.0
    assert limiter.check("a") is True


def test_prune_idle_keys_removes_entries_whose_window_has_fully_elapsed(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("control_plane.core.rate_limit.time.monotonic", lambda: clock["t"])
    limiter = SlidingWindowRateLimiter(max_events=5, window_seconds=10.0)
    limiter.check("idle-key")
    assert limiter.tracked_key_count() == 1
    clock["t"] += 11.0
    limiter.prune_idle_keys()
    assert limiter.tracked_key_count() == 0


def test_tracked_key_count_is_bounded_by_max_tracked_keys(monkeypatch):
    """Item 6: 'Bound/prune limiter memory.' A limiter whose key space
    is NOT attacker-constrained (unlike the real auth-failure limiter
    after this round's fix, which is keyed on the connecting address)
    must still never grow its dict without bound -- `check()` itself
    prunes idle keys inline once the tracked count reaches
    `max_tracked_keys`, so a burst of many distinct, now-idle keys
    cannot accumulate forever even if nothing ever calls
    `prune_idle_keys()` explicitly."""
    clock = {"t": 1000.0}
    monkeypatch.setattr("control_plane.core.rate_limit.time.monotonic", lambda: clock["t"])
    limiter = SlidingWindowRateLimiter(max_events=5, window_seconds=1.0, max_tracked_keys=10)

    for i in range(5):
        limiter.check(f"key-{i}")
    assert limiter.tracked_key_count() == 5

    # Let that entire first batch of keys' windows fully elapse before
    # adding more -- every one of them is now prunable.
    clock["t"] += 2.0

    for i in range(5, 30):
        limiter.check(f"key-{i}")

    assert limiter.tracked_key_count() <= 10
