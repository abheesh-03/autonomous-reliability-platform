"""Phase 3D incident lifecycle state machine.

A single, centralized, independently-testable source of truth for
which incident status transitions are legal — never scattered across
route handlers, SQL, or the webhook ingestion path. Both
`api/incidents.py` (the human/operator `PATCH .../status` endpoint)
and `ingestion/service.py` (Alertmanager-driven automatic resolution)
import from here rather than re-encoding any part of this table
themselves.

Transition matrix (also documented in
docs/architecture/phase-3d-incident-lifecycle.md):

    open          -> acknowledged, investigating, resolved
    acknowledged  -> investigating, resolved
    investigating -> remediating, resolved
    remediating   -> investigating, resolved
    resolved      -> closed
    closed        -> (none)

Rationale, briefly (full detail in the design doc):
- Some incidents recover before anyone acknowledges them, and
  investigation may begin without a separate acknowledgement step —
  hence open can reach resolved or investigating directly.
- Remediation can fail, requiring investigation to resume — hence
  remediating -> investigating is legal, not a dead end.
- A resolved incident is never reopened in place; a recurring
  condition produces a brand-new incident (Phase 3C's
  per-fingerprint, status-scoped partial unique index already makes
  this possible) while the previous resolved incident is preserved as
  history.
- Closing is an explicit administrative action a human takes on an
  already-resolved incident — Alertmanager never performs it
  automatically, and there is no path back out of closed.

A request whose target_status equals its own current/expected status
is NOT represented in this table (no status lists itself as a legal
"transition" target) — that is intentionally handled as a separate,
explicit no-op case by the caller (see api/incidents.py), not treated
as an entry in this matrix.
"""

from typing import Final

from control_plane.domain.incident import Status

ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "open": frozenset({"acknowledged", "investigating", "resolved"}),
    "acknowledged": frozenset({"investigating", "resolved"}),
    "investigating": frozenset({"remediating", "resolved"}),
    "remediating": frozenset({"investigating", "resolved"}),
    "resolved": frozenset({"closed"}),
    "closed": frozenset(),
}


def is_transition_allowed(current_status: str, target_status: str) -> bool:
    """True only if `target_status` is a legal forward transition from
    `current_status` per the matrix above. A status is never
    "allowed to transition to itself" here — same-status requests are
    a distinct, separately-handled no-op case (see module docstring)."""
    return target_status in ALLOWED_TRANSITIONS.get(current_status, frozenset())


def entering_resolved(target_status: str) -> bool:
    """True only when `target_status` is 'resolved' — the one case
    where resolved_at must be set as part of the transition. Every
    other transition (including resolved -> closed, the only legal
    move out of resolved) must leave resolved_at completely untouched,
    preserving the ORIGINAL resolution time rather than overwriting it
    with the closure time."""
    return target_status == "resolved"


__all__ = ["ALLOWED_TRANSITIONS", "Status", "entering_resolved", "is_transition_allowed"]
