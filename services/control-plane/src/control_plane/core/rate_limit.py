"""Phase 16 Gate 3/4: in-process rate limiting for the telemetry
ingestion path.

KNOWN LIMITATION (documented in docs/architecture/phase-16-secure-
telemetry-onboarding.md): this is an IN-PROCESS, single-instance
limiter -- a plain dict guarded by state kept on the FastAPI app, not a
shared store (Redis, etc.). It is real and effective against a single
abusive credential/caller hitting THIS process, and is the correct
scope for this round's "smallest coherent secure integration," but it
does NOT coordinate across multiple horizontally-scaled control-plane
replicas. A future production deployment running more than one replica
would need a shared backing store for this to remain effective at
scale -- explicitly out of scope here.

Two independent limiters are used by api/telemetry_ingest.py:
  - one keyed by credential_id, bounding ACCEPTED ingestion requests
    per credential (Gate 4: "Ingestion rate limits").
  - one keyed by credential_id-or-caller-IP, bounding AUTH FAILURES
    specifically -- a credential that fails verification repeatedly is
    far more likely to be a guessing attack than a legitimate client
    error, so this is a separate, stricter budget (Gate 3: "Rate-limit
    authentication failures").
"""

import time
from collections import deque


class SlidingWindowRateLimiter:
    """A real sliding-window counter, not a coarse fixed-window one (a
    fixed window lets up to 2x the nominal rate through across a window
    boundary) -- a deque of recent-event timestamps per key, trimmed to
    the window on every check. Bounded memory: a key with no recent
    activity is pruned the next time it is checked at all, and
    `prune_idle_keys` can be called periodically to bound memory for
    keys that simply stop being used.

    Item 6: memory is ALSO actively bounded, not merely "prunable if
    something remembers to call `prune_idle_keys`" -- every `check()`
    call that would grow the key count past `max_tracked_keys` prunes
    idle keys immediately, inline. A source sending one request each
    from many distinct fabricated identities (now impossible to turn
    into distinct rate-limit keys at all for the auth-failure limiter,
    see api/telemetry_auth.py's own correction -- but kept here as a
    defensive bound against any current or future caller of this class
    with a less-constrained key space) cannot grow this dict without
    bound.
    """

    def __init__(self, *, max_events: int, window_seconds: float, max_tracked_keys: int = 10_000) -> None:
        self._max_events = max_events
        self._window_seconds = window_seconds
        self._max_tracked_keys = max_tracked_keys
        self._events: dict[str, deque[float]] = {}

    def check(self, key: str) -> bool:
        """Returns True (and records this call as a consumed slot) if
        `key` is still within its budget; False (and records NOTHING)
        if the budget is already exhausted -- a rejected call never
        itself counts against the budget, so a caller who is
        rate-limited and backs off correctly is not penalized further
        for the rejected attempts themselves."""
        now = time.monotonic()
        if key not in self._events and len(self._events) >= self._max_tracked_keys:
            self.prune_idle_keys()
            if len(self._events) >= self._max_tracked_keys:
                # Nothing was idle (every tracked key is genuinely
                # active right now) -- a true hard memory bound still
                # requires evicting SOMETHING, so the single
                # least-recently-used key is dropped (its own budget
                # resets early; a bounded worst case is strictly
                # preferable to unbounded dict growth under a
                # sustained burst from many simultaneously-active
                # keys).
                oldest_key = min(
                    self._events, key=lambda k: self._events[k][-1] if self._events[k] else float("-inf")
                )
                del self._events[oldest_key]
        window = self._events.setdefault(key, deque())
        cutoff = now - self._window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._max_events:
            return False
        window.append(now)
        return True

    def prune_idle_keys(self) -> None:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        idle = [key for key, window in self._events.items() if not window or window[-1] < cutoff]
        for key in idle:
            del self._events[key]

    def tracked_key_count(self) -> int:
        """Test/observability seam -- never used for rate-limit logic
        itself."""
        return len(self._events)


# Gate 4: a real, instrumented client sending request-duration metrics
# every few seconds (batched) would need nowhere near this budget --
# 60 accepted ingestion requests/minute per credential is generous
# headroom for legitimate use while still bounding a misbehaving or
# compromised credential's worst-case write volume.
INGESTION_RATE_LIMITER = SlidingWindowRateLimiter(max_events=60, window_seconds=60.0)

# Gate 3: a real client's credential is correct on essentially every
# request (a typo'd token fails once, then the operator fixes their
# config) -- 10 failed-auth attempts/5 minutes per key is enough
# headroom for a one-off misconfiguration while still bounding a
# credential-guessing attempt to a slow trickle.
AUTH_FAILURE_RATE_LIMITER = SlidingWindowRateLimiter(max_events=10, window_seconds=300.0)
