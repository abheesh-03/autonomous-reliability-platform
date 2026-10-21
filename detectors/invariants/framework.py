"""Gate D: the reusable invariant-checking framework -- a plugin
registry, not a rewrite-the-engine-per-invariant design. A future
invariant (real or synthetic) is added by implementing one async
callable matching `InvariantChecker` and registering it; nothing else
in this package needs to change.

Note on scope (stated honestly, not quietly skipped): payment-service
and inventory-service were evaluated for a second real checker and
deliberately excluded -- NEITHER exposes any read-only, queryable
history (no persisted ledger, no GET-list endpoint; see Gate A's own
audit and this module's own test suite for a SYNTHETIC-only
demonstration plugin instead). Imposing an invariant with no real
backing read-only source would violate Gate D's own "do not impose an
invented invariant" requirement, so none was added here."""

from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Protocol

from detectors.schemas.invariant import InvariantCheckReport, InvariantDefinition


class InvariantChecker(Protocol):
    def __call__(self, window_start: datetime, window_end: datetime) -> Awaitable[InvariantCheckReport]: ...


@dataclass(frozen=True)
class RegisteredInvariant:
    definition: InvariantDefinition
    checker: InvariantChecker


class InvariantRegistry:
    """A plain, explicit list -- no dynamic plugin-discovery magic, no
    import-time side effects. A caller builds one, registers whatever
    checkers it has real evidence sources for, and runs them."""

    def __init__(self) -> None:
        self._invariants: list[RegisteredInvariant] = []

    def register(self, definition: InvariantDefinition, checker: InvariantChecker) -> None:
        if any(r.definition.invariant_id == definition.invariant_id for r in self._invariants):
            raise ValueError(f"invariant_id {definition.invariant_id!r} is already registered")
        self._invariants.append(RegisteredInvariant(definition=definition, checker=checker))

    @property
    def invariants(self) -> list[RegisteredInvariant]:
        return list(self._invariants)

    async def run_all(self, window_start: datetime, window_end: datetime) -> list[InvariantCheckReport]:
        return [await r.checker(window_start, window_end) for r in self._invariants]
