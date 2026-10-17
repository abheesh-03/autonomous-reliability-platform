"""Real-PostgreSQL transaction tests for the Phase 8 remediation domain
(V6__create_remediation_schema.sql / repositories/remediation_repository.py).

Deliberate, narrow exception to this test suite's usual "never touch a
real database" rule (see tests/conftest.py's own docstring) -- CAS
UPDATEs, idempotent ON CONFLICT handling, and the atomic
proposal+incident transaction this phase's entire safety model depends
on are exactly the kind of behavior a mocked repository cannot prove;
only a real connection can (Phase 8 §DATABASE TRANSACTION TESTS).

Every test runs inside ONE real transaction on its own session and
NEVER commits -- `rollback()` in a `finally` block is this test file's
only cleanup, leaving zero footprint on the real local dev database
regardless of outcome. Statements within the same uncommitted
transaction still see each other's effects (ordinary read-your-own-
writes), which is sufficient to exercise every CAS/idempotency path
here; actually proving data survives a real COMMIT is already covered
by api/incidents.py's own existing real-world usage and by
scripts/verify-remediation.sh's end-to-end acceptance run against the
real, committing API.

Gracefully SKIPPED when no real database is reachable (the normal fast
`make control-plane-test` Docker run, which has no postgres service
linked). Setting CONTROL_PLANE_REQUIRE_REAL_DB=true turns that skip
into a hard FAILURE instead -- used by CI's dedicated real-database
step, mirroring AGENT_RUNTIME_REQUIRE_REAL_DB / RETRIEVAL_REQUIRE_REAL_DB.

CI host-address wiring (post-GitHub-Actions-run-#35 fix): this file's
own `session` fixture deliberately does NOT call
`control_plane.core.config.DatabaseSettings.from_env()` (production
semantics there are UNCHANGED and still read plain `POSTGRES_HOST`,
defaulting to the Compose-internal DNS name `"postgres"`). CI's
dedicated real-database step runs pytest directly on the GitHub
Actions HOST (never inside a container on the Compose network), so it
must connect to PostgreSQL's HOST-PUBLISHED address
(`127.0.0.1:$POSTGRES_PORT`) -- but `tests/conftest.py` unconditionally
`setdefault()`s `POSTGRES_HOST=postgres.invalid` for every OTHER test
in this suite (an intentional safety net: ordinary unit tests must
never be able to silently reach a real database). Importing
conftest.py therefore poisons `POSTGRES_HOST` for this file too, and
`DatabaseSettings.from_env()` would try to resolve
`postgres.invalid`, which GitHub Actions' real DNS correctly refuses
to resolve -- `[Errno -2] Name or service not known` -- failing every
one of this file's 23 tests before any transaction logic ever ran.

Fixed via `_test_postgres_host`/`_test_postgres_port` below: two tiny,
PURE functions (unit-tested directly by
`test_test_postgres_host_ignores_the_poisoned_global_default` further
down, no real database required) that read dedicated,
real-database-test-only environment variables
(`CONTROL_PLANE_TEST_POSTGRES_HOST`/`CONTROL_PLANE_TEST_POSTGRES_PORT`,
defaulting to `127.0.0.1`/`$POSTGRES_PORT` or `5432`) -- never the
global `POSTGRES_HOST` conftest.py's safety default controls. This
never weakens that safety net for any OTHER test in this suite, and
normal unit tests remain exactly as incapable of reaching a real
database as before.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from control_plane.core.config import DatabaseSettings
from control_plane.db.engine import create_engine
from control_plane.repositories.incident_repository import IncidentRepository
from control_plane.repositories.remediation_repository import (
    IdempotencyConflictError,
    IllegalProposalTransitionError,
    RemediationRepository,
)


def _require_real_db() -> bool:
    return os.environ.get("CONTROL_PLANE_REQUIRE_REAL_DB", "").strip().lower() in ("1", "true", "yes")


def _unavailable(message: str) -> None:
    if _require_real_db():
        pytest.fail(message)
    pytest.skip(message)


def _test_postgres_host() -> str:
    """The HOST-REACHABLE PostgreSQL address for THIS file's own
    real-database tests only -- deliberately never `POSTGRES_HOST`
    (which `tests/conftest.py` intentionally poisons to
    `"postgres.invalid"` for every other, non-real-database test in
    this suite). Defaults to `127.0.0.1`, matching the published host
    port `docker-compose.yml`'s own `postgres` service always binds
    (`"${POSTGRES_PORT:-5432}:5432"`)."""
    return os.environ.get("CONTROL_PLANE_TEST_POSTGRES_HOST", "127.0.0.1")


def _test_postgres_port() -> int:
    """Same discipline as `_test_postgres_host` above. Falls back to
    the general `POSTGRES_PORT` (the real, intentionally-public
    host-side port every other real-database script in this platform
    already uses), then `5432` -- never the Compose-internal-only
    `POSTGRES_INTERNAL_PORT` production `DatabaseSettings.from_env()`
    uses, which is never meaningful from outside the Compose
    network."""
    return int(os.environ.get("CONTROL_PLANE_TEST_POSTGRES_PORT", os.environ.get("POSTGRES_PORT", "5432")))


def test_test_postgres_host_ignores_the_poisoned_global_default(monkeypatch):
    """Regression proof for GitHub Actions run #35's exact failure:
    even with `POSTGRES_HOST` poisoned to `tests/conftest.py`'s own
    `"postgres.invalid"` safety default, `_test_postgres_host()` must
    resolve to the real, host-reachable address -- never that poisoned
    value -- whenever `CONTROL_PLANE_TEST_POSTGRES_HOST` is set. Pure
    function, no real database required."""
    monkeypatch.setenv("POSTGRES_HOST", "postgres.invalid")
    monkeypatch.setenv("CONTROL_PLANE_TEST_POSTGRES_HOST", "127.0.0.1")
    assert _test_postgres_host() == "127.0.0.1"
    assert _test_postgres_host() != "postgres.invalid"


def test_test_postgres_host_defaults_to_127_0_0_1_even_without_the_override(monkeypatch):
    """Same proof, but relying purely on the function's own default --
    confirms the default itself is host-reachable, not merely that an
    explicit override can escape the poisoned value."""
    monkeypatch.setenv("POSTGRES_HOST", "postgres.invalid")
    monkeypatch.delenv("CONTROL_PLANE_TEST_POSTGRES_HOST", raising=False)
    assert _test_postgres_host() == "127.0.0.1"


def test_test_postgres_port_falls_back_to_postgres_port_then_5432(monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_TEST_POSTGRES_PORT", raising=False)
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    assert _test_postgres_port() == 5433

    monkeypatch.delenv("POSTGRES_PORT", raising=False)
    assert _test_postgres_port() == 5432

    monkeypatch.setenv("CONTROL_PLANE_TEST_POSTGRES_PORT", "6000")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    assert _test_postgres_port() == 6000


def test_production_from_env_is_unaffected_and_still_sees_the_poisoned_default(monkeypatch):
    """Preserves the OTHER half of the safety boundary: this real-
    database test file's own fix must never weaken conftest.py's
    global `POSTGRES_HOST` default for ordinary unit tests, nor change
    production `DatabaseSettings.from_env()`'s own semantics. Proves
    both directly: with the SAME poisoned value conftest.py's own
    `setdefault()` installs, `DatabaseSettings.from_env()` (the exact
    code path every OTHER service entrypoint/test uses) still resolves
    `host == "postgres.invalid"` -- completely unmodified and
    unaffected by `_test_postgres_host()`'s own, deliberately separate
    override above."""
    monkeypatch.setenv("POSTGRES_HOST", "postgres.invalid")
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "d")
    assert DatabaseSettings.from_env().host == "postgres.invalid"


@pytest.fixture
async def session():
    user = os.environ.get("POSTGRES_USER", "")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    database = os.environ.get("POSTGRES_DB", "")
    if not (user and password and database):
        _unavailable(
            "no real POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB configured -- skipping the real-database "
            "remediation transaction tests"
        )
        return

    settings = DatabaseSettings(
        host=_test_postgres_host(),
        port=_test_postgres_port(),
        user=user,
        password=password,
        database=database,
        pool_size=5,
        pool_pre_ping=True,
        pool_timeout_seconds=5.0,
        connect_timeout_seconds=5.0,
        command_timeout_seconds=10.0,
    )
    engine = create_engine(settings)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    real_session = sessionmaker()
    try:
        await real_session.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 -- connection failure means "skip" or "fail", decided by _unavailable
        await real_session.close()
        await engine.dispose()
        _unavailable(f"real database not reachable at {settings.host}:{settings.port}: {exc}")
        return

    try:
        yield real_session
    finally:
        await real_session.rollback()
        await real_session.close()
        await engine.dispose()


async def _make_incident(session, *, status: str) -> uuid.UUID:
    """A real `reliability.incidents` row, run-scoped
    (source_fingerprint is a fresh uuid4 every call, so it can never
    collide with real dev data or another test run), walked through the
    real lifecycle repository to reach `status` -- never a hand-rolled
    INSERT with a fabricated status, so this is exactly the same state
    a real incident would be in."""
    incident_repo = IncidentRepository(session)
    now = datetime.now(UTC)
    incident_id, created = await incident_repo.upsert_firing_incident(
        source="test",
        source_fingerprint=f"phase8-remediation-test-{uuid.uuid4()}",
        title="Phase 8 remediation transaction test incident",
        description=None,
        severity="critical",
        first_seen_at=now - timedelta(minutes=5),
        last_seen_at=now,
        occurrence_starts_at=now - timedelta(minutes=5),
    )
    assert created is True

    path = {
        "open": [],
        "investigating": [("open", "investigating")],
        "remediating": [("open", "investigating"), ("investigating", "remediating")],
    }[status]
    for expected, target in path:
        row = await incident_repo.transition_incident_status(
            incident_id, expected_status=expected, target_status=target, resolved_at=None
        )
        assert row is not None
    return incident_id


def _create_kwargs(
    incident_id: uuid.UUID,
    *,
    idempotency_key: str,
    reason: str = "test reason",
    agent_run_id: uuid.UUID | None = None,
) -> dict:
    # `agent_run_id` defaults to a FRESH uuid4 only when the caller
    # doesn't care about it -- a genuine retried request (the whole
    # point of idempotency_key) always carries the SAME agent_run_id as
    # its original attempt, since it is the same durable LangGraph run
    # retrying itself; callers asserting idempotent-replay behavior
    # must pass the identical agent_run_id both times, or this
    # intentionally looks like (and is correctly treated as) a
    # genuinely different/conflicting request.
    return dict(
        incident_id=incident_id,
        agent_run_id=agent_run_id if agent_run_id is not None else uuid.uuid4(),
        idempotency_key=idempotency_key,
        action_type="clear_payment_authorization_fault",
        target="payment-service",
        reason=reason,
        supporting_evidence_ids=["ev-1"],
        supporting_context_ids=["ctx-1"],
    )


# ---------------------------------------------------------------------
# Proposal creation idempotency
# ---------------------------------------------------------------------


async def test_create_proposal_same_idempotency_key_and_same_request_returns_existing_row(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    key = f"phase8-proposal:{uuid.uuid4()}"
    run_id = uuid.uuid4()  # the SAME agent run retries -- see _create_kwargs's own docstring

    first, created_first = await repo.create_proposal(**_create_kwargs(incident_id, idempotency_key=key, agent_run_id=run_id))
    second, created_second = await repo.create_proposal(**_create_kwargs(incident_id, idempotency_key=key, agent_run_id=run_id))

    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]

    total_stmt = sa.text("SELECT count(*) FROM reliability.remediation_proposals WHERE idempotency_key = :k")
    count = (await session.execute(total_stmt, {"k": key})).scalar_one()
    assert count == 1

    events_stmt = sa.text(
        "SELECT count(*) FROM reliability.remediation_events WHERE proposal_id = :pid AND event_type = 'proposed'"
    )
    proposed_count = (await session.execute(events_stmt, {"pid": first["id"]})).scalar_one()
    assert proposed_count == 1


async def test_create_proposal_rejects_an_oversized_evidence_id_even_bypassing_pydantic(session):
    """Phase 8 correction round (finding #6): the repository's own
    defensive backstop (never only the HTTP-layer Pydantic validation)
    -- a direct repository caller cannot smuggle an out-of-bounds id
    past the API layer."""
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    with pytest.raises(ValueError, match="supporting_evidence_ids"):
        await repo.create_proposal(
            **_create_kwargs(
                incident_id,
                idempotency_key=f"phase8-proposal:{uuid.uuid4()}",
            )
            | {"supporting_evidence_ids": ["e" * 201]}
        )


async def test_create_proposal_rejects_ids_whose_joined_length_exceeds_the_aggregate_bound(session):
    """Phase 8 correction round (finding #5, second pass): V6's own
    CHECK constraint bounds the array by BOTH `cardinality(...) <= 50`
    AND `char_length(array_to_string(..., ',')) <= 5000` -- many
    200-char ids can pass the per-element (<=200) and per-list-length
    (<=50) checks individually while still exceeding the AGGREGATE
    joined bound. The repository must catch this itself, before ever
    issuing the INSERT, not merely surface a raw PostgreSQL CHECK
    violation."""
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    many_ids = ["e" * 200 for _ in range(30)]  # 30 <= 50 elements, each == 200 chars
    assert len(",".join(many_ids)) > 5000

    with pytest.raises(ValueError, match="joined length"):
        await repo.create_proposal(
            **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
            | {"supporting_evidence_ids": many_ids}
        )

    # Nothing was inserted -- the rejection happened before the INSERT.
    count = (
        await session.execute(
            sa.text("SELECT count(*) FROM reliability.remediation_proposals WHERE incident_id = :iid"),
            {"iid": incident_id},
        )
    ).scalar_one()
    assert count == 0


async def test_create_proposal_same_key_conflicting_request_raises(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    key = f"phase8-proposal:{uuid.uuid4()}"
    run_id = uuid.uuid4()

    await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=key, reason="original reason", agent_run_id=run_id)
    )

    # Only `reason` differs -- isolates the "same key, different
    # semantic field" conflict case from any other field.
    with pytest.raises(IdempotencyConflictError):
        await repo.create_proposal(
            **_create_kwargs(incident_id, idempotency_key=key, reason="a DIFFERENT reason", agent_run_id=run_id)
        )


# ---------------------------------------------------------------------
# Approval: atomic with the incident lifecycle
# ---------------------------------------------------------------------


async def test_approve_atomically_transitions_incident_and_records_both_events(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )

    decided = await repo.decide(
        proposal["id"], expected_status="pending_approval", decision="approve", comment="looks good"
    )
    assert decided is not None
    assert decided["status"] == "approved"
    assert decided["decided_at"] is not None
    assert decided["decision_comment"] == "looks good"

    incident_row = (
        await session.execute(sa.text("SELECT status FROM reliability.incidents WHERE id = :id"), {"id": incident_id})
    ).mappings().first()
    assert incident_row["status"] == "remediating"

    remediation_events = (
        await session.execute(
            sa.text("SELECT event_type, actor_type FROM reliability.remediation_events WHERE proposal_id = :pid"),
            {"pid": proposal["id"]},
        )
    ).mappings().all()
    assert {"proposed", "approved"} <= {e["event_type"] for e in remediation_events}

    incident_events = (
        await session.execute(
            sa.text(
                "SELECT event_type, previous_status, new_status FROM reliability.incident_events "
                "WHERE incident_id = :iid AND new_status = 'remediating'"
            ),
            {"iid": incident_id},
        )
    ).mappings().all()
    assert len(incident_events) == 1
    assert incident_events[0]["previous_status"] == "investigating"


async def test_approve_fails_safely_when_incident_not_investigating(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="open")  # never reached 'investigating'
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )

    result = await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment=None)
    assert result is None  # caller (api/remediation.py) turns this into 409

    # Nothing mutated: proposal still pending_approval, incident still open.
    reloaded = await repo.get_by_id(proposal["id"])
    assert reloaded["status"] == "pending_approval"
    incident_row = (
        await session.execute(sa.text("SELECT status FROM reliability.incidents WHERE id = :id"), {"id": incident_id})
    ).mappings().first()
    assert incident_row["status"] == "open"


async def test_reject_never_touches_the_incident(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )

    decided = await repo.decide(
        proposal["id"], expected_status="pending_approval", decision="reject", comment="not safe right now"
    )
    assert decided["status"] == "rejected"

    incident_row = (
        await session.execute(sa.text("SELECT status FROM reliability.incidents WHERE id = :id"), {"id": incident_id})
    ).mappings().first()
    assert incident_row["status"] == "investigating"


async def test_decide_idempotent_replay_same_comment_returns_existing_without_duplicate_event(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )

    first = await repo.decide(proposal["id"], expected_status="pending_approval", decision="reject", comment="no")
    second = await repo.decide(proposal["id"], expected_status="pending_approval", decision="reject", comment="no")
    assert first["decided_at"] == second["decided_at"]

    count = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events WHERE proposal_id = :pid AND event_type = 'rejected'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert count == 1


async def test_decide_replay_with_different_comment_raises_conflict(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )

    await repo.decide(proposal["id"], expected_status="pending_approval", decision="reject", comment="first comment")
    with pytest.raises(IllegalProposalTransitionError):
        await repo.decide(
            proposal["id"], expected_status="pending_approval", decision="reject", comment="a DIFFERENT comment"
        )


async def test_decide_replay_of_approval_after_execution_started_is_idempotent(session):
    """Phase 8 correction round (finding #4): the approval decision's
    OWN lineage continues past 'approved' into 'executing' -- a
    replay of the SAME approve decision (same comment) arriving after
    execution has already begun must be a read-only idempotent replay
    of the CURRENT ('executing') row, never a 409 and never a
    regression back to 'approved'."""
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment="go ahead")
    await repo.start_execution(proposal["id"])

    replayed = await repo.decide(
        proposal["id"], expected_status="pending_approval", decision="approve", comment="go ahead"
    )
    assert replayed["status"] == "executing"

    approved_events = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events WHERE proposal_id = :pid AND event_type = 'approved'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert approved_events == 1


async def test_decide_replay_of_approval_after_succeeded_is_idempotent(session):
    """Same as above, repeated after the proposal has reached the
    terminal 'succeeded' status -- the approval decision's lineage
    extends all the way to a terminal outcome."""
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment=None)
    await repo.start_execution(proposal["id"])
    await repo.record_execution_result(proposal["id"], outcome="succeeded", detail="cleared")

    replayed = await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment=None)
    assert replayed["status"] == "succeeded"

    approved_events = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events WHERE proposal_id = :pid AND event_type = 'approved'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert approved_events == 1


async def test_decide_replay_of_approval_with_different_comment_after_executing_raises_conflict(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment="original")
    await repo.start_execution(proposal["id"])

    with pytest.raises(IllegalProposalTransitionError):
        await repo.decide(
            proposal["id"], expected_status="pending_approval", decision="approve", comment="a DIFFERENT comment"
        )


async def test_reject_decision_after_approval_lineage_raises_conflict(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment=None)
    await repo.start_execution(proposal["id"])

    with pytest.raises(IllegalProposalTransitionError):
        await repo.decide(proposal["id"], expected_status="pending_approval", decision="reject", comment=None)


async def test_approve_decision_after_rejected_raises_conflict(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    await repo.decide(proposal["id"], expected_status="pending_approval", decision="reject", comment=None)

    with pytest.raises(IllegalProposalTransitionError):
        await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment=None)


# ---------------------------------------------------------------------
# Execution bookkeeping: idempotency + failure rollback
# ---------------------------------------------------------------------


async def _approved_proposal(session, repo) -> tuple[uuid.UUID, dict]:
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    await repo.decide(proposal["id"], expected_status="pending_approval", decision="approve", comment=None)
    return incident_id, proposal


async def test_start_execution_refuses_pending_proposal_by_returning_it_unchanged(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    result = await repo.start_execution(proposal["id"])
    assert result["status"] == "pending_approval"  # tool-gateway's own caller refuses to proceed for this


async def test_start_execution_is_idempotent_across_retries(session):
    repo = RemediationRepository(session)
    _incident_id, proposal = await _approved_proposal(session, repo)

    first = await repo.start_execution(proposal["id"])
    second = await repo.start_execution(proposal["id"])  # simulates a crash-and-retry
    assert first["status"] == "executing"
    assert second["status"] == "executing"
    assert first["execution_started_at"] == second["execution_started_at"]

    count = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events "
                "WHERE proposal_id = :pid AND event_type = 'execution_started'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert count == 1


async def test_execution_result_succeeded_is_idempotent(session):
    repo = RemediationRepository(session)
    _incident_id, proposal = await _approved_proposal(session, repo)
    await repo.start_execution(proposal["id"])

    first = await repo.record_execution_result(proposal["id"], outcome="succeeded", detail="cleared")
    second = await repo.record_execution_result(proposal["id"], outcome="succeeded", detail="cleared")
    assert first["status"] == "succeeded"
    assert second["execution_completed_at"] == first["execution_completed_at"]

    count = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events "
                "WHERE proposal_id = :pid AND event_type = 'execution_succeeded'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert count == 1


async def test_execution_result_failed_rolls_incident_back_to_investigating(session):
    repo = RemediationRepository(session)
    incident_id, proposal = await _approved_proposal(session, repo)
    await repo.start_execution(proposal["id"])

    result = await repo.record_execution_result(proposal["id"], outcome="failed", detail="payment unreachable")
    assert result["status"] == "failed"

    incident_row = (
        await session.execute(sa.text("SELECT status FROM reliability.incidents WHERE id = :id"), {"id": incident_id})
    ).mappings().first()
    assert incident_row["status"] == "investigating"

    remediation_events = {
        e["event_type"]
        for e in (
            await session.execute(
                sa.text("SELECT event_type FROM reliability.remediation_events WHERE proposal_id = :pid"),
                {"pid": proposal["id"]},
            )
        ).mappings().all()
    }
    assert "execution_failed" in remediation_events

    incident_rollback_events = (
        await session.execute(
            sa.text(
                "SELECT previous_status, new_status FROM reliability.incident_events "
                "WHERE incident_id = :iid AND previous_status = 'remediating' AND new_status = 'investigating'"
            ),
            {"iid": incident_id},
        )
    ).mappings().all()
    assert len(incident_rollback_events) == 1


async def test_execution_result_is_idempotent_when_failed_twice(session):
    repo = RemediationRepository(session)
    incident_id, proposal = await _approved_proposal(session, repo)
    await repo.start_execution(proposal["id"])
    await repo.record_execution_result(proposal["id"], outcome="failed", detail="first failure")

    # Replaying the same 'failed' outcome must not attempt a SECOND
    # incident rollback (the incident is already back in
    # 'investigating', not 'remediating' -- a naive unconditional retry
    # could otherwise be a silent no-op OR, worse, could misfire against
    # whatever state the incident happens to be in by then).
    second = await repo.record_execution_result(proposal["id"], outcome="failed", detail="first failure")
    assert second["status"] == "failed"

    count = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events "
                "WHERE proposal_id = :pid AND event_type = 'execution_failed'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert count == 1

    incident_row = (
        await session.execute(sa.text("SELECT status FROM reliability.incidents WHERE id = :id"), {"id": incident_id})
    ).mappings().first()
    assert incident_row["status"] == "investigating"


async def test_execution_result_conflicting_terminal_outcome_raises(session):
    repo = RemediationRepository(session)
    _incident_id, proposal = await _approved_proposal(session, repo)
    await repo.start_execution(proposal["id"])
    await repo.record_execution_result(proposal["id"], outcome="succeeded", detail=None)

    with pytest.raises(IllegalProposalTransitionError):
        await repo.record_execution_result(proposal["id"], outcome="failed", detail="too late")


# ---------------------------------------------------------------------
# Atomicity: the whole transaction rolls back if the audit-event INSERT
# itself fails, even after the proposal/incident UPDATEs already ran
# against this real connection (Phase 8 correction round, finding #7).
# ---------------------------------------------------------------------


class _FailingIncidentAuditRemediationRepository(RemediationRepository):
    """Test-only deterministic failure injection: the REAL proposal and
    incident status UPDATEs (and, for the approve path, the REAL
    'approved' remediation event too) genuinely execute against this
    real database connection first -- only the LAST write in each of
    decide()'s approve path and record_execution_result()'s failure
    path (`_record_incident_event`, the incident's own audit event) is
    overridden to raise. This is exactly the dangerous boundary the
    original Phase 8 spec required proof of: "proposal update succeeds,
    incident update succeeds, AUDIT EVENT INSERT FAILS -> entire
    transaction rolls back", using a real database, never a mock."""

    async def _record_incident_event(self, *args, **kwargs):
        raise RuntimeError("simulated incident audit event insert failure")


async def test_approve_rolls_back_entirely_when_incident_audit_event_insert_fails(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )

    failing_repo = _FailingIncidentAuditRemediationRepository(session)
    # The exception must propagate OUT of the `async with` block so
    # SQLAlchemy performs a real `ROLLBACK TO SAVEPOINT` (see
    # test_remediation_events_are_append_only's own docstring for why
    # catching it INSIDE the block would instead leave the connection
    # aborted). The SAVEPOINT isolates just this failing attempt,
    # preserving the incident/proposal rows created earlier in this
    # same test for the assertions below.
    with pytest.raises(RuntimeError, match="simulated incident audit event insert failure"):
        async with session.begin_nested():
            await failing_repo.decide(
                proposal["id"], expected_status="pending_approval", decision="approve", comment=None
            )

    # Fresh reads prove NO partial effect survived: not the proposal
    # update, not the incident update, not either audit event -- a
    # real "no half-approved proposal, no incident stuck remediating"
    # proof against a real database.
    reloaded_proposal = await repo.get_by_id(proposal["id"])
    assert reloaded_proposal["status"] == "pending_approval"
    assert reloaded_proposal["decided_at"] is None

    incident_row = (
        await session.execute(sa.text("SELECT status FROM reliability.incidents WHERE id = :id"), {"id": incident_id})
    ).mappings().first()
    assert incident_row["status"] == "investigating"

    approved_events = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events WHERE proposal_id = :pid AND event_type = 'approved'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert approved_events == 0

    incident_transition_events = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.incident_events WHERE incident_id = :iid "
                "AND previous_status = 'investigating' AND new_status = 'remediating'"
            ),
            {"iid": incident_id},
        )
    ).scalar_one()
    assert incident_transition_events == 0


async def test_execution_result_failed_rolls_back_entirely_when_incident_audit_event_insert_fails(session):
    repo = RemediationRepository(session)
    incident_id, proposal = await _approved_proposal(session, repo)
    await repo.start_execution(proposal["id"])

    failing_repo = _FailingIncidentAuditRemediationRepository(session)
    with pytest.raises(RuntimeError, match="simulated incident audit event insert failure"):
        async with session.begin_nested():
            await failing_repo.record_execution_result(proposal["id"], outcome="failed", detail="simulated")

    # No half-failed proposal, no incident stuck in 'remediating'.
    reloaded_proposal = await repo.get_by_id(proposal["id"])
    assert reloaded_proposal["status"] == "executing"
    assert reloaded_proposal["execution_completed_at"] is None

    incident_row = (
        await session.execute(sa.text("SELECT status FROM reliability.incidents WHERE id = :id"), {"id": incident_id})
    ).mappings().first()
    assert incident_row["status"] == "remediating"

    failed_events = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.remediation_events WHERE proposal_id = :pid AND event_type = 'execution_failed'"
            ),
            {"pid": proposal["id"]},
        )
    ).scalar_one()
    assert failed_events == 0

    incident_rollback_events = (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM reliability.incident_events WHERE incident_id = :iid "
                "AND previous_status = 'remediating' AND new_status = 'investigating'"
            ),
            {"iid": incident_id},
        )
    ).scalar_one()
    assert incident_rollback_events == 0


# ---------------------------------------------------------------------
# Append-only enforcement (real trigger, not merely application
# discipline) -- sanity companion to the migration-level smoke check.
# ---------------------------------------------------------------------


async def test_remediation_events_are_append_only(session):
    repo = RemediationRepository(session)
    incident_id = await _make_incident(session, status="investigating")
    proposal, _ = await repo.create_proposal(
        **_create_kwargs(incident_id, idempotency_key=f"phase8-proposal:{uuid.uuid4()}")
    )
    row = (
        await session.execute(
            sa.text("SELECT id FROM reliability.remediation_events WHERE proposal_id = :pid LIMIT 1"),
            {"pid": proposal["id"]},
        )
    ).mappings().first()

    # The exception must propagate OUT of the `async with` block so
    # SQLAlchemy's own nested-transaction context manager performs a
    # real `ROLLBACK TO SAVEPOINT` on exit (not a `RELEASE SAVEPOINT`,
    # which would itself fail against a connection Postgres has already
    # marked aborted) -- catching it INSIDE the block instead (an
    # earlier draft's bug, caught by this very test run against the
    # real database) leaves the connection aborted for every statement
    # after it, including this test's own cleanup rollback.
    with pytest.raises(Exception, match="append-only"):
        async with session.begin_nested():
            await session.execute(
                sa.text("UPDATE reliability.remediation_events SET event_type = 'rejected' WHERE id = :id"),
                {"id": row["id"]},
            )
