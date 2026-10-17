"""Shared test fixtures.

Phase 8 added a real `lifespan` to this service (main.py) -- the
fault-control tokens and the one process-local `AuthorizationFaultState`
are only set up there (see main.py's own docstring). `TestClient(app)`
only runs that lifespan when entered as a context manager (confirmed
empirically: a bare, non-`with` module-level client, this test suite's
PRE-Phase-8 convention, never ran startup at all, so
`request.app.state.fault_state` would raise `AttributeError` on the
very first request) -- so every test in this suite now goes through
this one `client` fixture instead of a bare module-level TestClient,
the same convention services/control-plane/tests/conftest.py already
establishes.

Deterministic, known-in-tests Bearer tokens let test_faults.py exercise
both "correct token" and "incorrect token" paths, and assert the two
are not interchangeable, without depending on whatever a real local
.env happens to contain -- same convention
services/control-plane/tests/conftest.py already establishes for its
own webhook/lifecycle tokens.
"""

import os

os.environ.setdefault("PAYMENT_FAULT_INJECTION_TOKEN", "test-fault-injection-token")
os.environ.setdefault("PAYMENT_REMEDIATION_TOKEN", "test-payment-remediation-token")
# Enabled by default in this unit-test environment so
# test_faults.py's own "enable succeeds" path can be exercised; the
# dedicated disabled-by-default test overrides this explicitly via
# monkeypatch + a fresh TestClient, never relying on module import
# order.
os.environ.setdefault("PAYMENT_FAULT_INJECTION_ENABLED", "true")

INJECTION_TOKEN = os.environ["PAYMENT_FAULT_INJECTION_TOKEN"]
REMEDIATION_TOKEN = os.environ["PAYMENT_REMEDIATION_TOKEN"]

import pytest
from fastapi.testclient import TestClient

from payment_service.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
