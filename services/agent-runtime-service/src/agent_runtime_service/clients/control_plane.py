"""Client for control-plane's incident read API (Phase 7 node 1,
load_incident) AND, as of Phase 8, its remediation-proposal domain
(propose_remediation / await_human_approval / verify_recovery).

Phase 7 surface (unchanged): GET /api/v1/incidents/{id} --
unauthenticated/read-only. Never calls PATCH
/api/v1/incidents/{id}/status or POST
/internal/v1/alertmanager/webhook -- this client has no method for
either, and this service is never given either of control-plane's
write-capable Bearer tokens (CONTROL_PLANE_WEBHOOK_TOKEN /
CONTROL_PLANE_LIFECYCLE_TOKEN).

Phase 8 surface (additive):
  POST /internal/v1/remediation-proposals -- authenticated with
    CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN (the ONE remediation
    credential this service holds). Creates a proposal only -- cannot
    approve/reject and cannot record an execution result; this client
    has no method for either of those two capabilities, and this
    service is never given CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN or
    CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN.
  GET /api/v1/remediation-proposals/{id} -- unauthenticated/read-only,
    same local-development policy as the incident GET above. This is
    what lets await_human_approval's resume path independently fetch
    the TRUSTED human decision from control-plane, never from a
    caller-supplied value (Phase 8 §HUMAN DECISION SOURCE OF TRUTH).
"""

import logging
import uuid

import httpx
from pydantic import ValidationError

from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.remediation import RemediationProposal

logger = logging.getLogger("agent_runtime_service.control_plane")


class IncidentNotFoundError(Exception):
    pass


class ControlPlaneUnavailableError(Exception):
    pass


class ControlPlaneOutputError(Exception):
    """The response was reachable (200) but did not match the
    expected IncidentSnapshot shape -- never trusted into durable graph
    state regardless (Phase 7 correction round, finding #5 -- same
    discipline as InvestigatorOutputError)."""


class RemediationProposalNotFoundError(Exception):
    """control-plane returned 404 for this proposal id."""


class RemediationProposalConflictError(Exception):
    """control-plane returned 409 -- e.g. the same idempotency_key
    already exists with a DIFFERENT, conflicting proposal. Terminal:
    retrying the identical request would not help (Phase 7's own
    TERMINAL-vs-TRANSIENT split, Phase 8 §PROPOSAL IDEMPOTENCY)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class RemediationProposalCreateAmbiguousError(Exception):
    """Phase 8 correction round (finding #2): `POST
    /internal/v1/remediation-proposals` COMMITS the proposal (+ its
    'proposed' event) BEFORE control-plane ever builds its HTTP
    response -- so an HTTP 5xx, a malformed 200/201 body, or a 200/201
    body that fails shape validation does NOT prove the proposal was
    never created; it may already exist, durably, under this exact
    idempotency_key. Deliberately a DISTINCT type from
    `ControlPlaneOutputError` -- this ambiguity is specific to a
    MUTATING endpoint's own response handling, and conflating the two
    would make `get_incident`'s/`get_remediation_proposal`'s unrelated
    read-only GET validation failures incorrectly retryable too (a
    malformed GET response proves nothing was ever mutated -- those
    keep raising `ControlPlaneOutputError`, terminal, unchanged).

    Left UNCAUGHT by graph/nodes.py::propose_remediation (same
    TRANSIENT/RETRYABLE convention as `ControlPlaneUnavailableError`)
    so the checkpoint is never committed and the run remains resumable
    at `propose_remediation`: a retried `create_remediation_proposal`
    call uses the SAME deterministic idempotency_key
    (`"phase8-proposal:<run_id>"`) and safely converges on the SAME
    proposal via control-plane's own idempotent creation logic --
    never a duplicate, and no separate reconciliation read is needed
    here (unlike tool-gateway's execute() ambiguity, correction round
    finding #1) because the create endpoint's own idempotency key
    already makes a blind retry of the identical POST safe."""


class ControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        connect_timeout: float,
        request_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
        remediation_proposal_token: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, connect=connect_timeout)
        # Real network by default (transport=None); tests inject an
        # httpx.MockTransport here, the same seam-based convention
        # investigator-service's own control-plane client tests use.
        self._transport = transport
        # Phase 8: the ONE remediation credential this service holds --
        # sent ONLY on create_remediation_proposal below, never on any
        # GET (both the incident GET and the proposal GET remain
        # genuinely unauthenticated/read-only).
        self._remediation_proposal_token = remediation_proposal_token

    async def get_incident(self, incident_id: str) -> IncidentSnapshot:
        url = f"{self._base_url}/api/v1/incidents/{incident_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

        if resp.status_code == 404:
            raise IncidentNotFoundError(incident_id)
        if resp.status_code != 200:
            raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise ControlPlaneOutputError(f"control-plane returned a non-JSON response from {url}") from exc

        try:
            return IncidentSnapshot.model_validate(body)
        except ValidationError as exc:
            # Never concatenate str(exc) or the raw body -- pydantic's
            # ValidationError message includes each failing field's
            # actual input_value verbatim (Phase 7 correction round,
            # finding #5). Safe, structural metadata only.
            logger.warning("control-plane response failed shape validation (%d error(s))", exc.error_count())
            raise ControlPlaneOutputError(
                "control-plane response did not match the expected response contract"
            ) from exc

    # ------------------------------------------------------------------
    # Phase 8: remediation proposals
    # ------------------------------------------------------------------

    async def create_remediation_proposal(
        self,
        *,
        incident_id: uuid.UUID | str,
        agent_run_id: uuid.UUID | str,
        idempotency_key: str,
        action_type: str,
        target: str,
        reason: str,
        supporting_evidence_ids: list[str],
        supporting_context_ids: list[str],
    ) -> RemediationProposal:
        """POST /internal/v1/remediation-proposals. Idempotent on
        control-plane's own side (Phase 8 §PROPOSAL IDEMPOTENCY): the
        SAME idempotency_key with the SAME semantic fields returns the
        existing proposal rather than creating a duplicate -- this
        client does not itself retry or special-case that; it simply
        reports whatever control-plane returns."""
        url = f"{self._base_url}/internal/v1/remediation-proposals"
        body = {
            "incident_id": str(incident_id),
            "agent_run_id": str(agent_run_id),
            "idempotency_key": idempotency_key,
            "action_type": action_type,
            "target": target,
            "reason": reason,
            "supporting_evidence_ids": list(supporting_evidence_ids),
            "supporting_context_ids": list(supporting_context_ids),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._remediation_proposal_token}"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

        if resp.status_code == 409:
            try:
                detail = resp.json().get("detail", "idempotency conflict")
            except ValueError:
                detail = "idempotency conflict"
            raise RemediationProposalConflictError(str(detail))
        # Phase 8 correction round (finding #2): every remaining
        # "unexpected" outcome here -- an HTTP 5xx/other unexpected
        # status, a malformed body, or a body that fails shape
        # validation -- is raised as RemediationProposalCreateAmbiguousError,
        # NEVER ControlPlaneOutputError: this endpoint already committed
        # the proposal BEFORE building its response, so none of these
        # prove the proposal was never created.
        if resp.status_code not in (200, 201):
            raise RemediationProposalCreateAmbiguousError(
                f"control-plane returned HTTP {resp.status_code} for {url} -- the proposal may already "
                "exist durably under this idempotency_key"
            )

        try:
            response_body = resp.json()
        except ValueError as exc:
            raise RemediationProposalCreateAmbiguousError(
                f"control-plane returned a non-JSON response from {url} -- the proposal may already "
                "exist durably under this idempotency_key"
            ) from exc

        try:
            return RemediationProposal.model_validate(response_body)
        except ValidationError as exc:
            logger.warning(
                "control-plane remediation-proposal CREATE response failed shape validation (%d error(s))",
                exc.error_count(),
            )
            raise RemediationProposalCreateAmbiguousError(
                "control-plane's create-remediation-proposal response did not match the expected contract "
                "-- the proposal may already exist durably under this idempotency_key"
            ) from exc

    async def get_remediation_proposal(self, proposal_id: uuid.UUID | str) -> RemediationProposal:
        """GET /api/v1/remediation-proposals/{id} -- unauthenticated.
        This is the ONLY place either api/agent_runs.py's resume path
        (Phase 8 §HUMAN DECISION SOURCE OF TRUTH) or
        graph/nodes.py::verify_recovery reads a proposal's real,
        trusted status."""
        url = f"{self._base_url}/api/v1/remediation-proposals/{proposal_id}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            raise ControlPlaneUnavailableError(f"could not reach control-plane at {url}: {exc}") from exc

        if resp.status_code == 404:
            raise RemediationProposalNotFoundError(str(proposal_id))
        if resp.status_code != 200:
            raise ControlPlaneUnavailableError(f"control-plane returned HTTP {resp.status_code} for {url}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise ControlPlaneOutputError(f"control-plane returned a non-JSON response from {url}") from exc

        try:
            return RemediationProposal.model_validate(body)
        except ValidationError as exc:
            logger.warning(
                "control-plane remediation-proposal response failed shape validation (%d error(s))",
                exc.error_count(),
            )
            raise ControlPlaneOutputError(
                "control-plane response did not match the expected remediation-proposal contract"
            ) from exc
