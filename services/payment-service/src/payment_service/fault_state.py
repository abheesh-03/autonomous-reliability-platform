"""Phase 8: a controlled, LOCAL-DEVELOPMENT-ONLY authorization fault.

This is deliberately the simplest possible fault mechanism: ONE
boolean, held in process memory, guarded by a plain `threading.Lock`
(payment-service's route handlers are synchronous FastAPI functions,
so this is the correct primitive here -- NOT an asyncio lock, and NOT
`sync.RWMutex`, which is a Go primitive and does not exist in this
Python service).

Honest, stated limitations (Phase 8 §PAYMENT SERVICE CONTROLLED FAULT):

- This state is PROCESS-LOCAL, single-process demo state. It is never
  persisted to PostgreSQL, never shared across multiple payment-service
  replicas (this platform only ever runs one), and is reset to inactive
  by any payment-service process restart. A real production fault-
  injection mechanism would need durable, externally-visible state;
  this one deliberately does not, because Phase 8's payment-service
  fault exists ONLY to produce a real, demonstrable, recoverable
  incident for this platform's own local acceptance run -- see
  docs/architecture/phase-8-human-approval-remediation.md.
- Exactly one fault mode exists: "every authorization request fails".
  There is no arbitrary delay injection, no arbitrary status-code
  selection, no arbitrary exception injection, and no per-request
  targeting -- a single, global, boolean switch, nothing more.
"""

import threading


class AuthorizationFaultState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False

    def enable(self) -> None:
        with self._lock:
            self._active = True

    def clear(self) -> dict:
        """Idempotent: clearing an already-inactive fault is always a
        safe no-op. Returns `{"active": False, "changed": bool}` --
        `changed` is True only if this call actually transitioned the
        state from active to inactive, never a claim about any
        previous call."""
        with self._lock:
            changed = self._active
            self._active = False
        return {"active": False, "changed": changed}

    def is_active(self) -> bool:
        with self._lock:
            return self._active
