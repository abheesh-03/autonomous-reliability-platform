"""Database access for reliability.remediation_proposals/remediation_events
(Phase 8).

Deliberately NOT an ORM-mapped declarative model -- same bare
`sa.table()`/`sa.column()` Core-table convention
repositories/incident_repository.py already establishes: the schema is
owned exclusively by Flyway (database/migrations/), this module only
ever reads or writes individual rows into it, with real parameter
binding throughout.

This repository shares its `AsyncSession` with IncidentRepository (both
are constructed from the SAME request-scoped session -- see
api/dependencies.py) specifically so `decide()` (approve) and
`record_execution_result()` (on failure) can perform the remediation
mutation AND the incident-lifecycle mutation AND their respective audit
events in ONE atomic transaction -- never two separate commits that
could leave one applied without the other.
"""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.domain.lifecycle import is_transition_allowed
from control_plane.domain.remediation import MAX_ID_CHARS, MAX_IDS_JOINED_CHARS
from control_plane.repositories.incident_repository import incidents_table

remediation_proposals_table = sa.table(
    "remediation_proposals",
    sa.column("id"),
    sa.column("incident_id"),
    sa.column("agent_run_id"),
    sa.column("idempotency_key"),
    sa.column("action_type"),
    sa.column("target"),
    sa.column("reason"),
    sa.column("supporting_evidence_ids", ARRAY(sa.Text())),
    sa.column("supporting_context_ids", ARRAY(sa.Text())),
    sa.column("status"),
    sa.column("proposed_at"),
    sa.column("updated_at"),
    sa.column("decided_at"),
    sa.column("decision_comment"),
    sa.column("execution_started_at"),
    sa.column("execution_completed_at"),
    schema="reliability",
)

remediation_events_table = sa.table(
    "remediation_events",
    sa.column("id"),
    sa.column("proposal_id"),
    sa.column("event_type"),
    sa.column("actor_type"),
    sa.column("occurred_at"),
    sa.column("metadata", JSONB),
    schema="reliability",
)


class IdempotencyConflictError(Exception):
    """Same idempotency_key, but the new request's semantic fields
    (incident_id/agent_run_id/action_type/target/reason/evidence ids)
    differ from the proposal already stored under that key -- the
    caller (api/remediation.py) turns this into HTTP 409. Deliberately
    NOT silently returning the stale existing proposal in this case:
    that would hide a genuinely different request behind a fabricated
    "success"."""


class IllegalProposalTransitionError(Exception):
    """The requested status transition is not legal from the
    proposal's own current status -- e.g. deciding an already-decided
    proposal with a different decision, or an execution-result call
    arriving for a proposal that was never started. The caller turns
    this into HTTP 409."""


DecisionLiteral = Literal["approve", "reject"]


def _validate_bounded_ids(ids: Sequence[str], *, field_name: str) -> None:
    """Defense-in-depth backstop (Phase 8 correction round, findings
    #6 and #5-second-pass): the HTTP API path already rejects an
    out-of-bounds id -- per-element via domain.remediation.BoundedId,
    and the AGGREGATE joined-string bound via
    domain.remediation._validate_joined_length -- before ever reaching
    this repository, but a caller that constructs this repository
    directly (a test, or a future internal caller) bypasses that
    entirely. This keeps BOTH bounds true at the data layer regardless
    of how it was called, mirroring V6's own CHECK constraint exactly:
    `cardinality(...) <= 50 AND char_length(array_to_string(..., ','))
    <= 5000` -- the second is never implied by the first plus the
    per-element bound (50 * 200 = 10000 > 5000), so both must be
    checked independently."""
    for item in ids:
        if not item or len(item) > MAX_ID_CHARS:
            raise ValueError(
                f"{field_name} contains an invalid id (must be non-empty and at most {MAX_ID_CHARS} characters)"
            )
    joined_length = len(",".join(ids))
    if joined_length > MAX_IDS_JOINED_CHARS:
        raise ValueError(
            f"{field_name}: joined length ({joined_length} chars, comma-separated) exceeds the "
            f"maximum of {MAX_IDS_JOINED_CHARS} chars"
        )


def _proposal_from_row(row: Mapping) -> dict:
    d = dict(row)
    d["supporting_evidence_ids"] = list(d.get("supporting_evidence_ids") or [])
    d["supporting_context_ids"] = list(d.get("supporting_context_ids") or [])
    return d


class RemediationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    # ------------------------------------------------------------------
    # Creation (idempotent)
    # ------------------------------------------------------------------

    async def create_proposal(
        self,
        *,
        incident_id: uuid.UUID,
        agent_run_id: uuid.UUID,
        idempotency_key: str,
        action_type: str,
        target: str,
        reason: str,
        supporting_evidence_ids: Sequence[str],
        supporting_context_ids: Sequence[str],
    ) -> tuple[dict, bool]:
        """Atomically create-or-return-existing, keyed on
        `idempotency_key` (UNIQUE in V6). Returns (proposal, created).

        On a genuine new insert: proposal + 'proposed' event, same
        transaction, same convention as
        IncidentRepository.upsert_firing_incident's own create+event
        pairing.

        On conflict (a proposal already exists under this exact
        idempotency_key -- the expected shape of a retried request
        after a crash, Phase 7's own documented at-least-once reality):
        compared field-by-field against the stored row. An identical
        semantic request returns that existing row, created=False, and
        writes NOTHING new -- not even a duplicate 'proposed' event.
        A request that differs in any semantic field raises
        IdempotencyConflictError -- the caller 409s rather than
        silently either overwriting the original or returning a
        proposal that doesn't match what was actually asked for this
        time.
        """
        _validate_bounded_ids(supporting_evidence_ids, field_name="supporting_evidence_ids")
        _validate_bounded_ids(supporting_context_ids, field_name="supporting_context_ids")
        insert_stmt = (
            pg_insert(remediation_proposals_table)
            .values(
                incident_id=incident_id,
                agent_run_id=agent_run_id,
                idempotency_key=idempotency_key,
                action_type=action_type,
                target=target,
                reason=reason,
                supporting_evidence_ids=list(supporting_evidence_ids),
                supporting_context_ids=list(supporting_context_ids),
            )
            .on_conflict_do_nothing(index_elements=[remediation_proposals_table.c.idempotency_key])
            .returning(remediation_proposals_table)
        )
        result = await self._session.execute(insert_stmt)
        row = result.mappings().first()

        if row is not None:
            proposal = _proposal_from_row(row)
            await self._record_event(
                proposal["id"],
                event_type="proposed",
                actor_type="agent",
                metadata={"incident_id": str(incident_id)},
            )
            return proposal, True

        # Conflict: a row already exists under this idempotency_key.
        existing = await self.get_by_id(idempotency_key=idempotency_key)
        if existing is None:  # pragma: no cover -- defensive; the UNIQUE conflict guarantees a row exists
            raise RuntimeError(f"idempotency_key {idempotency_key!r} conflicted but no row could be read back")

        same_request = (
            existing["incident_id"] == incident_id
            and existing["agent_run_id"] == agent_run_id
            and existing["action_type"] == action_type
            and existing["target"] == target
            and existing["reason"] == reason
            and existing["supporting_evidence_ids"] == list(supporting_evidence_ids)
            and existing["supporting_context_ids"] == list(supporting_context_ids)
        )
        if not same_request:
            raise IdempotencyConflictError(
                f"idempotency_key {idempotency_key!r} already exists with different proposal fields"
            )
        return existing, False

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_by_id(
        self, proposal_id: uuid.UUID | None = None, *, idempotency_key: str | None = None
    ) -> dict | None:
        if proposal_id is not None:
            stmt = sa.select(remediation_proposals_table).where(remediation_proposals_table.c.id == proposal_id)
        elif idempotency_key is not None:
            stmt = sa.select(remediation_proposals_table).where(
                remediation_proposals_table.c.idempotency_key == idempotency_key
            )
        else:
            raise ValueError("either proposal_id or idempotency_key is required")
        result = await self._session.execute(stmt)
        row = result.mappings().first()
        return _proposal_from_row(row) if row is not None else None

    async def list_for_incident(
        self, incident_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[dict], int]:
        base = sa.select(remediation_proposals_table).where(remediation_proposals_table.c.incident_id == incident_id)
        total = (
            await self._session.execute(sa.select(sa.func.count()).select_from(base.subquery()))
        ).scalar_one()
        page_stmt = base.order_by(
            remediation_proposals_table.c.proposed_at.desc(), remediation_proposals_table.c.id.desc()
        ).limit(limit).offset(offset)
        result = await self._session.execute(page_stmt)
        rows = [_proposal_from_row(r) for r in result.mappings().all()]
        return rows, total

    async def get_events(self, proposal_id: uuid.UUID, *, limit: int, offset: int) -> tuple[Sequence[Mapping], int]:
        total_stmt = (
            sa.select(sa.func.count())
            .select_from(remediation_events_table)
            .where(remediation_events_table.c.proposal_id == proposal_id)
        )
        total = (await self._session.execute(total_stmt)).scalar_one()
        page_stmt = (
            sa.select(remediation_events_table)
            .where(remediation_events_table.c.proposal_id == proposal_id)
            .order_by(remediation_events_table.c.occurred_at.asc(), remediation_events_table.c.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(page_stmt)
        rows = result.mappings().all()
        return rows, total

    # ------------------------------------------------------------------
    # Human decision (atomic with the owning incident's lifecycle)
    # ------------------------------------------------------------------

    async def decide(
        self,
        proposal_id: uuid.UUID,
        *,
        expected_status: str,
        decision: DecisionLiteral,
        comment: str | None,
    ) -> dict | None:
        """Approve or reject a proposal.

        APPROVE is atomic with the owning incident's
        investigating -> remediating transition (Phase 8's own
        mandatory invariant): this single method performs the
        proposal CAS UPDATE, the incident CAS UPDATE, AND both audit
        events (remediation 'approved' + incident 'status_transition'),
        all against `self._session`, so if ANY of them fails the
        whole thing rolls back together when the caller's session
        closes without a commit -- there is no window where a
        proposal is 'approved' but the incident never moved, or vice
        versa. If the incident is not currently 'investigating', this
        method returns None (ambiguous zero-rows-affected, exactly
        IncidentRepository.transition_incident_status's own
        convention) and the caller (api/remediation.py) resolves that
        into a 409 WITHOUT ever touching the proposal row -- approval
        must fail safely if the incident has since moved.

        REJECT only ever touches the proposal row -- the incident is
        explicitly never transitioned (Phase 8's own requirement:
        "Rejecting a proposal does NOT move the incident to
        remediating").

        Idempotency (REQUIRED, Phase 8 correction round #8, extended by
        correction round #4): a REPEAT of the exact same (decision,
        normalized comment) against an ALREADY-DECIDED proposal returns
        that existing row with no new write at all -- no duplicate
        event, no decided_at/comment overwrite, no state regression. A
        decision that conflicts with the proposal's actual current
        status (different decision already recorded, or a replay with
        a DIFFERENT comment than what was actually recorded) raises
        IllegalProposalTransitionError -- the caller 409s. The
        original human decision/comment is never silently overwritten.

        Correction round (finding #4): an APPROVED proposal's own
        lineage does not stop at 'approved' -- it legitimately
        continues on to 'executing', 'succeeded', or 'failed' as
        execution progresses. The ORIGINAL approval decision has
        already been durably applied in every one of those statuses,
        so an identical replay of that SAME approve decision (the same
        normalized comment) arriving AFTER execution has already begun
        must still be treated as an idempotent replay -- returning the
        CURRENT proposal read-only, never regressing it back to
        'approved' and never duplicating the 'approved' event. Only a
        REJECT decision's own lineage is a single terminal status
        ('rejected' itself, handled by the `existing["status"] ==
        target_status` branch below) -- a rejected proposal never
        progresses any further, so no equivalent lineage exists for it.
        """
        normalized_comment = comment.strip() if comment else None
        target_status = "approved" if decision == "approve" else "rejected"
        approved_lineage = ("approved", "executing", "succeeded", "failed")

        existing = await self.get_by_id(proposal_id)
        if existing is None:
            return None

        if decision == "approve" and existing["status"] in approved_lineage:
            # Possibly an idempotent replay of an already-applied
            # approval -- even after execution has since progressed --
            # or a genuine conflict if the comment differs from what
            # was actually recorded. Comparing against the STORED
            # comment (not re-deciding) is what keeps this a read-only
            # idempotent path rather than a second write.
            stored_comment = existing.get("decision_comment")
            if existing.get("decided_at") is not None and stored_comment == normalized_comment:
                return existing
            raise IllegalProposalTransitionError(
                f"proposal {proposal_id} was already decided ('approved') with a different comment"
            )

        if existing["status"] == target_status:
            # decision == "reject" replay (an approve replay against an
            # 'approved'-lineage status is already handled above).
            stored_comment = existing.get("decision_comment")
            if stored_comment == normalized_comment:
                return existing
            raise IllegalProposalTransitionError(
                f"proposal {proposal_id} was already decided ({target_status!r}) with a different comment"
            )

        if existing["status"] != expected_status:
            # Neither "already in the target state" (handled above) nor
            # "currently in the expected state" -- a genuine stale
            # expected_status or an illegal transition (e.g. deciding
            # an 'executing'/'succeeded'/'failed' proposal at all,
            # which is never legal). The caller resolves this into a
            # precise 409.
            raise IllegalProposalTransitionError(
                f"proposal {proposal_id} is currently {existing['status']!r}, not {expected_status!r}"
            )
        if expected_status != "pending_approval":
            raise IllegalProposalTransitionError(
                f"proposal {proposal_id} cannot be decided from status {expected_status!r}"
            )

        now = datetime.now(UTC)

        if decision == "reject":
            stmt = (
                sa.update(remediation_proposals_table)
                .where(
                    remediation_proposals_table.c.id == proposal_id,
                    remediation_proposals_table.c.status == "pending_approval",
                )
                .values(status="rejected", decided_at=now, decision_comment=normalized_comment)
                .returning(remediation_proposals_table)
            )
            result = await self._session.execute(stmt)
            row = result.mappings().first()
            if row is None:
                raise IllegalProposalTransitionError(f"proposal {proposal_id} was concurrently modified")
            await self._record_event(
                proposal_id,
                event_type="rejected",
                actor_type="operator",
                metadata={"comment": normalized_comment} if normalized_comment else {},
            )
            return _proposal_from_row(row)

        # decision == "approve": atomic with the incident transition.
        incident_id = existing["incident_id"]
        incident_row = (
            await self._session.execute(sa.select(incidents_table).where(incidents_table.c.id == incident_id))
        ).mappings().first()
        if incident_row is None or incident_row["status"] != "investigating":
            # The incident must be in 'investigating' for an approval
            # to be legal -- fail safely, touch NOTHING. Distinguished
            # from a stale proposal status (handled above) because the
            # proposal itself IS still pending_approval here; it is the
            # INCIDENT that has drifted.
            return None
        if not is_transition_allowed("investigating", "remediating"):  # pragma: no cover -- defensive
            raise IllegalProposalTransitionError("investigating -> remediating is not a legal incident transition")

        proposal_stmt = (
            sa.update(remediation_proposals_table)
            .where(
                remediation_proposals_table.c.id == proposal_id,
                remediation_proposals_table.c.status == "pending_approval",
            )
            .values(status="approved", decided_at=now, decision_comment=normalized_comment)
            .returning(remediation_proposals_table)
        )
        proposal_result = await self._session.execute(proposal_stmt)
        proposal_row = proposal_result.mappings().first()
        if proposal_row is None:
            raise IllegalProposalTransitionError(f"proposal {proposal_id} was concurrently modified")

        incident_stmt = (
            sa.update(incidents_table)
            .where(incidents_table.c.id == incident_id, incidents_table.c.status == "investigating")
            .values(status="remediating")
            .returning(incidents_table.c.id)
        )
        incident_result = await self._session.execute(incident_stmt)
        if incident_result.mappings().first() is None:
            raise IllegalProposalTransitionError(f"incident {incident_id} was concurrently modified")

        await self._record_event(
            proposal_id,
            event_type="approved",
            actor_type="operator",
            metadata={"comment": normalized_comment} if normalized_comment else {},
        )
        await self._record_incident_event(
            incident_id,
            event_type="status_transition",
            actor_type="operator",
            previous_status="investigating",
            new_status="remediating",
            metadata={"remediation_proposal_id": str(proposal_id)},
        )
        return _proposal_from_row(proposal_row)

    # ------------------------------------------------------------------
    # Execution bookkeeping (tool-gateway only, idempotent)
    # ------------------------------------------------------------------

    async def start_execution(self, proposal_id: uuid.UUID) -> dict | None:
        """approved -> executing (idempotent re-entry: executing stays
        executing, no duplicate event). pending_approval/rejected ->
        returns the existing row UNCHANGED (the caller, tool-gateway,
        refuses to proceed for either). succeeded/failed -> returns
        the existing TERMINAL row unchanged, so a caller can recognize
        'this already finished' without this method ever regressing a
        terminal proposal back to 'executing'."""
        existing = await self.get_by_id(proposal_id)
        if existing is None:
            return None
        if existing["status"] != "approved":
            # pending_approval/rejected: the caller refuses outright.
            # executing: idempotent retry -- return as-is so the caller
            # continues the SAME in-flight execution/verification
            # without writing a second 'execution_started' event.
            # succeeded/failed: terminal -- return as-is so the caller
            # treats this as already-finished rather than restarting it.
            return existing

        now = datetime.now(UTC)
        stmt = (
            sa.update(remediation_proposals_table)
            .where(
                remediation_proposals_table.c.id == proposal_id,
                remediation_proposals_table.c.status == "approved",
            )
            .values(status="executing", execution_started_at=now)
            .returning(remediation_proposals_table)
        )
        result = await self._session.execute(stmt)
        row = result.mappings().first()
        if row is None:
            # Lost a race to another concurrent start -- re-read and
            # return whatever the winner left behind (still a safe,
            # idempotent outcome from this caller's point of view).
            return await self.get_by_id(proposal_id)

        await self._record_event(proposal_id, event_type="execution_started", actor_type="executor", metadata={})
        return _proposal_from_row(row)

    async def record_execution_result(
        self, proposal_id: uuid.UUID, *, outcome: Literal["succeeded", "failed"], detail: str | None
    ) -> dict | None:
        """executing -> succeeded|failed, idempotent: if the proposal
        is ALREADY in the requested terminal status, returns it
        unchanged with no duplicate event (tolerates the tool-gateway
        retrying its own bookkeeping call after a crash between the
        action succeeding and this call being acknowledged). A
        conflicting terminal call (e.g. reporting 'failed' for a
        proposal already recorded 'succeeded') raises
        IllegalProposalTransitionError -- the caller 409s rather than
        silently flipping an already-terminal result.

        On 'failed': atomically also rolls the owning incident back
        remediating -> investigating (Phase 8 correction round #6 --
        a failed remediation must never leave the incident stuck in
        'remediating' forever) and records BOTH a remediation
        'execution_failed' event and an incident 'status_transition'
        audit event, in the SAME transaction as the proposal's own
        status update. If the incident is not in 'remediating' at that
        moment (unexpected, but handled defensively), the incident
        transition is skipped -- the proposal/remediation-event side
        still records the real failure; see this method's own
        in-code comment for why the whole thing does not abort instead.
        """
        existing = await self.get_by_id(proposal_id)
        if existing is None:
            return None

        if existing["status"] == outcome:
            # Idempotent replay of an already-recorded terminal result.
            return existing
        if existing["status"] in ("succeeded", "failed"):
            raise IllegalProposalTransitionError(
                f"proposal {proposal_id} already has a different terminal result ({existing['status']!r})"
            )
        if existing["status"] != "executing":
            raise IllegalProposalTransitionError(
                f"proposal {proposal_id} is {existing['status']!r}, not 'executing' -- cannot record a result"
            )

        now = datetime.now(UTC)
        stmt = (
            sa.update(remediation_proposals_table)
            .where(
                remediation_proposals_table.c.id == proposal_id,
                remediation_proposals_table.c.status == "executing",
            )
            .values(status=outcome, execution_completed_at=now)
            .returning(remediation_proposals_table)
        )
        result = await self._session.execute(stmt)
        row = result.mappings().first()
        if row is None:
            raise IllegalProposalTransitionError(f"proposal {proposal_id} was concurrently modified")

        event_type = "execution_succeeded" if outcome == "succeeded" else "execution_failed"
        await self._record_event(
            proposal_id,
            event_type=event_type,
            actor_type="executor",
            metadata={"detail": detail} if detail else {},
        )

        if outcome == "failed":
            incident_id = existing["incident_id"]
            incident_stmt = (
                sa.update(incidents_table)
                .where(incidents_table.c.id == incident_id, incidents_table.c.status == "remediating")
                .values(status="investigating")
                .returning(incidents_table.c.id)
            )
            incident_result = await self._session.execute(incident_stmt)
            if incident_result.mappings().first() is not None:
                # actor_type='operator': incident_events' own vocabulary
                # (V3/V4, never modified by Phase 8) only has
                # 'alertmanager' (fully-automatic alert ingestion) and
                # 'operator' (an authenticated, non-Alertmanager write
                # path) -- this transition is control-plane's own
                # authenticated executor-triggered rollback, which is
                # categorically closer to 'operator' than to a raw
                # alert-ingestion event. metadata.resolution_source
                # disambiguates it honestly as execution-triggered, not
                # a literal human click -- the same "use metadata for
                # the nuance the bare actor_type vocabulary can't
                # express" convention
                # resolve_active_incident_for_fingerprint already uses
                # for Alertmanager's own automatic resolution.
                await self._record_incident_event(
                    incident_id,
                    event_type="status_transition",
                    actor_type="operator",
                    previous_status="remediating",
                    new_status="investigating",
                    metadata={"resolution_source": "remediation_execution_failed", "proposal_id": str(proposal_id)},
                )
            # If the incident was NOT in 'remediating' (e.g. a human
            # already moved it elsewhere, or it was independently
            # resolved concurrently) -- the real execution failure is
            # still honestly recorded on the proposal/remediation-event
            # side above; forcing an incident rollback it is no longer
            # eligible for would itself be the bug.

        return _proposal_from_row(row)

    # ------------------------------------------------------------------
    # Private event-recording helpers
    # ------------------------------------------------------------------

    async def _record_event(
        self, proposal_id: uuid.UUID, *, event_type: str, actor_type: str, metadata: Mapping[str, object]
    ) -> None:
        stmt = sa.insert(remediation_events_table).values(
            proposal_id=proposal_id, event_type=event_type, actor_type=actor_type, metadata=dict(metadata)
        )
        await self._session.execute(stmt)

    async def _record_incident_event(
        self,
        incident_id: uuid.UUID,
        *,
        event_type: str,
        actor_type: str,
        previous_status: str | None,
        new_status: str,
        metadata: Mapping[str, object],
    ) -> None:
        # Deliberately a local, minimal insert against
        # reliability.incident_events (never importing
        # IncidentRepository._record_event, which is private) -- same
        # table, same session/transaction, same shape rules V3/V4
        # already enforce at the database level.
        from control_plane.repositories.incident_repository import incident_events_table

        stmt = sa.insert(incident_events_table).values(
            incident_id=incident_id,
            event_type=event_type,
            actor_type=actor_type,
            previous_status=previous_status,
            new_status=new_status,
            metadata=dict(metadata),
        )
        await self._session.execute(stmt)
