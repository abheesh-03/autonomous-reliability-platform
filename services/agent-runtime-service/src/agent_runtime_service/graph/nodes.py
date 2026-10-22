"""The four Phase 7 graph nodes (Phase 7 §INITIAL PHASE 7 GRAPH). A
small, explicit graph -- deliberately not a fake multi-node
"autonomous" architecture (Phase 7 §WHY NO AGENT TOOL LOOP YET).

Node functions are built by `build_nodes(...)` (a factory, not module-
level singletons) so the real HTTP clients (and this service's own
bounds) are injected explicitly -- the same seam-based testing
philosophy every other service in this platform already uses: tests
inject fake client doubles, never a mocked httpx/LangGraph internal.

Failure handling (Phase 7 correction round #3 -- TRANSIENT vs
TERMINAL): a dependency failure is either a durable, business-level
fact about THIS incident/request, or a transient unavailability of a
downstream service that will very likely succeed once that dependency
recovers. These are handled differently, deliberately:

  - TERMINAL (caught here, routed to `finalize` with `status="failed"`,
    never resumable again -- `next` becomes empty): `IncidentNotFoundError`
    (the incident genuinely does not exist -- retrying without a
    different incident_id can never succeed), `ControlPlaneOutputError`,
    and `InvestigatorOutputError` (control-plane/investigator-service
    returned a 2xx response that did not match its own documented
    contract -- an incompatible/invalid upstream shape, not a temporary
    outage; retrying the identical request against the identical
    contract violation would not help); and an oversized-but-shape-valid
    investigator response (`error_code="investigator_output_too_large"`,
    correction round follow-up finding #3) -- a 2xx response that IS
    shape-valid but whose serialized size exceeds this service's own
    configured persistence ceiling, equally not something retrying the
    identical request would fix.
  - TRANSIENT/RETRYABLE (deliberately left UNCAUGHT): `ControlPlaneUnavailableError`
    and `InvestigatorUnavailableError`. Letting these propagate means
    LangGraph's last successfully committed checkpoint remains the
    resume point (`next` stays non-empty, pointing at the SAME node)
    -- exactly the same durable-crash-recovery mechanism
    test_checkpoint_durability.py already proves for a raw, unclassified
    exception. The API layer (api/agent_runs.py) catches these two
    specific types around its `ainvoke()` calls and translates them
    into a safe, generic HTTP response -- it never lets the raw
    exception reach a caller, and it never synthesizes a fake
    "failed"/terminal graph state for what is, from the graph's own
    checkpoint perspective, simply "not done yet."

This means a genuinely UNEXPECTED exception (a real bug, not any of
the four classified outcomes above) is ALSO left to propagate uncaught
-- indistinguishable, from the graph's point of view, from the two
transient cases above, which is the honest reality: LangGraph cannot
tell "the dependency was down" from "something else went wrong" apart
from the checkpoint remaining resumable either way.
"""

import logging
from datetime import UTC, datetime, timedelta

from langgraph.types import interrupt

from agent_runtime_service.clients.control_plane import (
    ControlPlaneClient,
    ControlPlaneOutputError,
    IncidentNotFoundError,
    RemediationProposalConflictError,
    RemediationProposalNotFoundError,
)
from agent_runtime_service.clients.investigator import InvestigatorClient, InvestigatorOutputError
from agent_runtime_service.clients.tool_gateway import (
    ToolGatewayAmbiguousExecutionError,
    ToolGatewayClient,
    ToolGatewayOutputError,
    ToolGatewayRefusedError,
)
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.graph.state import AgentGraphState
from agent_runtime_service.text_safety import bound_and_redact, hard_bound

logger = logging.getLogger("agent_runtime_service.graph.nodes")

# Phase 8 §DETERMINISTIC ACTION POLICY: the one, and only, allowlisted
# action/target -- mirrors tool-gateway's own Go allowlist
# (internal/allowlist/allowlist.go) and database/migrations/
# V6__create_remediation_schema.sql's own CHECK constraints exactly.
# Never derived from LLM output; a pure, hardcoded constant.
REMEDIATION_ACTION_TYPE = "clear_payment_authorization_fault"
REMEDIATION_TARGET = "payment-service"

# Phase 12B-D §GATE 4 DETERMINISTIC REMEDIATION POLICY: the ONE
# Kubernetes action/target pair -- mirrors tool-gateway's own widened
# Go allowlist and database/migrations/
# V7__add_kubernetes_remediation_action.sql's own combined CHECK
# constraint exactly. Never derived from LLM output.
K8S_REMEDIATION_ACTION_TYPE = "restart_allowlisted_deployment"
K8S_REMEDIATION_TARGET = "Deployment/reliability-sandbox/crashloop-demo"
K8S_REMEDIATION_TARGET_CLUSTER = "kind-reliability-lab"
K8S_REMEDIATION_TARGET_NAMESPACE = "reliability-sandbox"
K8S_REMEDIATION_TARGET_DEPLOYMENT_NAME = "crashloop-demo"

# Correction round (Issue 1): a detector_id is only ever treated as
# capable of authorizing THIS Kubernetes action if it reports a
# confirmed-failure-class detector result -- mirrors
# detectors/kubernetes/detectors.py's own 3 failure-pattern detector
# ids whose CONFIRMED result genuinely corresponds to the allowlisted
# Deployment's own targeted failure (CrashLoopBackOff/ImagePullBackOff/
# ErrImagePull/rollout failure). oom_killed and
# pod_readiness_degradation are deliberately EXCLUDED: a restart does
# not address an OOM resource-limit problem (Gate 4's own stated
# limitation) or an unexplained readiness degradation with no
# confirmed cause.
_K8S_CONFIRMED_FAILURE_DETECTOR_IDS = frozenset(
    {"crash_loop_backoff", "image_pull_backoff", "deployment_rollout_failure"}
)

# Correction round (Issue 1): a Kubernetes incident's own persisted
# evidence must be this fresh (relative to wall-clock "now") to ever
# authorize a proposal -- a previous, stale observation must never
# establish a CURRENT failure. Mirrors control-plane's own
# ingestion-time future-skew bound
# (ingestion/kubernetes_service.py's MAX_FUTURE_SKEW_SECONDS) with a
# symmetric PAST bound here, enforced again at proposal time (defense
# in depth: evidence that was fresh when ingested can still go stale
# by the time an agent run actually reaches propose_remediation).
K8S_EVIDENCE_MAX_STALENESS = timedelta(minutes=15)

# Must match observability/prometheus/rules/alerts.yml's
# CheckoutServerErrors alert `annotations.summary` EXACTLY --
# control-plane's ingestion/mapping.py sets an incident's `title` to
# the alert's own `summary` annotation when one is present (which this
# rule always provides), so this is the real, structured signal this
# service has for "this incident corresponds to the existing
# CheckoutServerErrors condition" (Phase 8 §DETERMINISTIC ACTION
# POLICY). Honest, stated limitation (see
# docs/architecture/phase-8-human-approval-remediation.md): reliability.incidents
# does not persist the Alertmanager alert name itself, so this is a
# title-text coupling to the alert rule's own annotation, not a
# first-class alertname column -- if that annotation text changes,
# this constant must change with it.
_REMEDIATION_POLICY_ALERT_TITLE = "checkout-service is returning HTTP 5xx errors"

# A defensive ceiling on how many evidence/context ids a single
# proposal ever carries -- mirrors
# V6__create_remediation_schema.sql's own `cardinality(...) <= 50`
# CHECK constraint exactly, so a request this service builds can never
# itself be the reason control-plane 422s/409s it.
MAX_SUPPORTING_IDS = 50


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_detail(text: str, max_chars: int) -> str:
    """Bounded, defense-in-depth truncation -- every exception message
    reaching this point already excludes raw secrets/SDK text by
    construction (see clients/*.py's own exception classes), this only
    guards against an unexpectedly long message, the same discipline
    Phase 5/6 already apply to every other piece of external text.
    Delegates to `text_safety.hard_bound` so the returned string
    (including any truncation suffix) is a REAL hard bound -- never
    `max_chars` plus the suffix's own length (correction round
    follow-up, finding #1)."""
    return hard_bound(text, max_chars)


def build_nodes(
    control_plane_client: ControlPlaneClient,
    investigator_client: InvestigatorClient,
    bounds: RuntimeBounds,
    tool_gateway_client: ToolGatewayClient | None = None,
):
    """Returns the node callables, each a plain
    `async def (state) -> dict` LangGraph node function. Phase 7's
    original four (load_incident/run_investigation/
    evaluate_investigation/finalize) plus Phase 8's four new ones
    (propose_remediation/await_human_approval/execute_remediation/
    verify_recovery). `tool_gateway_client` is optional ONLY so
    existing Phase 7-era unit tests that construct a graph without any
    remediation capability at all keep working unmodified; the real
    service (main.py) always provides one."""

    async def load_incident(state: AgentGraphState) -> dict:
        # ControlPlaneUnavailableError is deliberately NOT caught here --
        # see the module docstring's TERMINAL vs TRANSIENT/RETRYABLE
        # split. It propagates uncaught, leaving this node's checkpoint
        # un-committed and the thread resumable at `load_incident` again.
        try:
            incident = await control_plane_client.get_incident(state["incident_id"])
        except IncidentNotFoundError:
            return {
                "status": "failed",
                "error_code": "incident_not_found",
                "error_detail": "no incident exists with this id",
                "current_node": "load_incident",
                "completed_nodes": ["load_incident"],
                "updated_at": _now_iso(),
            }
        except ControlPlaneOutputError as exc:
            # TERMINAL, symmetric with InvestigatorOutputError below: a
            # 2xx response that did not match control-plane's own
            # documented contract is an incompatible/invalid upstream
            # shape, not a temporary outage.
            return {
                "status": "failed",
                "error_code": "control_plane_output_invalid",
                "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
                "current_node": "load_incident",
                "completed_nodes": ["load_incident"],
                "updated_at": _now_iso(),
            }

        return {
            "incident_snapshot": bound_and_redact(
                incident.model_dump(mode="json"), max_text_chars=bounds.max_incident_text_chars
            ),
            "current_node": "load_incident",
            "completed_nodes": ["load_incident"],
            "updated_at": _now_iso(),
        }

    async def run_investigation(state: AgentGraphState) -> dict:
        # InvestigatorUnavailableError is deliberately NOT caught here --
        # same TRANSIENT/RETRYABLE reasoning as load_incident above.
        try:
            report = await investigator_client.investigate(state["incident_id"])
        except InvestigatorOutputError as exc:
            return {
                "status": "failed",
                "error_code": "investigator_output_invalid",
                "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
                "current_node": "run_investigation",
                "completed_nodes": ["run_investigation"],
                "updated_at": _now_iso(),
            }

        # Phase 7 correction round (follow-up), finding #3: Phase 5/6
        # bound individual evidence/prompt fields, but impose no
        # UNIVERSAL ceiling on the investigator's own output as a
        # whole -- a shape-valid report can still be arbitrarily large
        # (many observations/hypotheses/evidence items, each with its
        # own bounded-but-nonzero text). The invariant Phase 7 itself
        # must uphold is narrower and absolute: no successful graph
        # checkpoint may ever contain a report whose serialized
        # representation exceeds this service's own configured ceiling.
        # Measured via pydantic's own canonical JSON serialization (the
        # real wire-equivalent form), never a hand-rolled encoding.
        # Distinct from InvestigatorUnavailableError: a 2xx response
        # that is simply too large to persist is a valid connectivity
        # result with an unacceptable persistence shape/size, not an
        # outage -- terminal, not retryable, the same reasoning as
        # InvestigatorOutputError's own shape-mismatch case.
        serialized_bytes = len(report.model_dump_json().encode("utf-8"))
        if serialized_bytes > bounds.max_investigation_report_bytes:
            return {
                "status": "failed",
                "error_code": "investigator_output_too_large",
                "error_detail": _safe_detail(
                    f"investigator-service response serialized size ({serialized_bytes} bytes) "
                    f"exceeds the configured limit ({bounds.max_investigation_report_bytes} bytes)",
                    bounds.max_error_detail_chars,
                ),
                "current_node": "run_investigation",
                "completed_nodes": ["run_investigation"],
                "updated_at": _now_iso(),
            }

        return {
            "investigation_report": report.model_dump(mode="json"),
            "validation_notes": list(report.validation_notes),
            "current_node": "run_investigation",
            "completed_nodes": ["run_investigation"],
            "updated_at": _now_iso(),
        }

    async def evaluate_investigation(state: AgentGraphState) -> dict:
        report = state.get("investigation_report")
        quality = classify_investigation(report) if report else "inconclusive"
        return {
            "result_quality": quality,
            "current_node": "evaluate_investigation",
            "completed_nodes": ["evaluate_investigation"],
            "updated_at": _now_iso(),
        }

    async def finalize(state: AgentGraphState) -> dict:
        now = _now_iso()
        final_status = "failed" if state.get("status") == "failed" else "completed"
        return {
            "status": final_status,
            "completed_at": now,
            "updated_at": now,
            "current_node": "finalize",
            "completed_nodes": ["finalize"],
        }

    async def propose_remediation(state: AgentGraphState) -> dict:
        """Phase 8 §DETERMINISTIC ACTION POLICY. The LLM/investigation
        never chooses an executable action here -- this node checks a
        small, deterministic set of structured conditions (never
        parsed from LLM prose) and, only if ALL of them hold, creates
        ONE allowlisted proposal. If no policy matches, this node
        creates NOTHING -- the run still finalizes normally, with
        `remediation_status="not_applicable"`."""
        now = _now_iso()
        not_applicable = {
            "remediation_status": "not_applicable",
            "current_node": "propose_remediation",
            "completed_nodes": ["propose_remediation"],
            "updated_at": now,
        }

        incident_snapshot = state.get("incident_snapshot") or {}
        source = incident_snapshot.get("source")

        if source == "alertmanager":
            policy_matches = (
                incident_snapshot.get("severity") == "critical"
                and incident_snapshot.get("title") == _REMEDIATION_POLICY_ALERT_TITLE
                and bool(state.get("investigation_report"))
            )
        elif source == "kubernetes":
            # Phase 12B-D: the Kubernetes policy branch deliberately
            # does NOT inspect incident_snapshot for cluster/namespace/
            # resource identity (this service's own documented boundary
            # -- domain/incident_snapshot.py -- is a bounded incident
            # snapshot, never its audit-event history). It defers
            # ENTIRELY to tool-gateway's own fresh, independent
            # precondition read below, exactly like the payment branch
            # defers to get_capability() rather than trusting any
            # hypothesis text.
            policy_matches = bool(state.get("investigation_report"))
        else:
            policy_matches = False

        if not policy_matches or tool_gateway_client is None:
            return not_applicable

        if source == "kubernetes":
            return await _propose_kubernetes_remediation(
                state, tool_gateway_client, control_plane_client, bounds, now, not_applicable
            )

        # Independent, deterministic precondition check -- never
        # trusts a hypothesis merely because it mentions "payment":
        # the one thing that actually gates proposal creation here is
        # tool-gateway's own read-only report of the REAL controlled
        # fault's current state.
        try:
            capability = await tool_gateway_client.get_capability()
        except ToolGatewayOutputError as exc:
            return {
                "status": "failed",
                "error_code": "tool_gateway_output_invalid",
                "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
                "current_node": "propose_remediation",
                "completed_nodes": ["propose_remediation"],
                "updated_at": now,
            }
        # ToolGatewayUnavailableError is deliberately NOT caught here --
        # same TRANSIENT/RETRYABLE reasoning as load_incident/
        # run_investigation above.

        if not (
            capability.action_type == REMEDIATION_ACTION_TYPE
            and capability.target == REMEDIATION_TARGET
            and capability.precondition_met
        ):
            return not_applicable

        evidence_ids = _collect_supporting_evidence_ids(state.get("investigation_report"))
        context_ids = _collect_supporting_context_ids(state.get("investigation_report"))
        reason = _safe_detail(
            "deterministic policy match: alertmanager-sourced critical incident matching the "
            "CheckoutServerErrors condition, with an existing investigation and tool-gateway "
            "independently reporting the controlled payment authorization fault as active",
            bounds.max_error_detail_chars,
        )

        try:
            proposal = await control_plane_client.create_remediation_proposal(
                incident_id=state["incident_id"],
                agent_run_id=state["run_id"],
                idempotency_key=f"phase8-proposal:{state['run_id']}",
                action_type=REMEDIATION_ACTION_TYPE,
                target=REMEDIATION_TARGET,
                reason=reason,
                supporting_evidence_ids=evidence_ids,
                supporting_context_ids=context_ids,
            )
        except RemediationProposalConflictError as exc:
            # TERMINAL: the same idempotency key already exists with a
            # DIFFERENT, conflicting proposal -- retrying the identical
            # request would never resolve this.
            return {
                "status": "failed",
                "error_code": "remediation_proposal_conflict",
                "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
                "current_node": "propose_remediation",
                "completed_nodes": ["propose_remediation"],
                "updated_at": now,
            }
        # RemediationProposalCreateAmbiguousError deliberately NOT
        # caught (Phase 8 correction round, finding #2): control-plane
        # already commits the proposal + its 'proposed' event BEFORE
        # ever building its HTTP response, so an HTTP 5xx, a malformed
        # body, or a shape-invalid body does NOT prove creation never
        # happened. Left uncaught -- same TRANSIENT/RETRYABLE
        # convention as ControlPlaneUnavailableError immediately below
        # -- so this node's checkpoint is never committed and the run
        # stays resumable at propose_remediation. ControlPlaneOutputError
        # deliberately NOT caught here either -- create_remediation_proposal
        # never raises it (only RemediationProposalCreateAmbiguousError,
        # for exactly the ambiguous cases above); ControlPlaneOutputError
        # remains reserved for read-only GET shape failures elsewhere in
        # this module (load_incident, verify_recovery), which genuinely
        # are terminal.
        #
        # ControlPlaneUnavailableError deliberately NOT caught --
        # TRANSIENT/RETRYABLE, same as load_incident above. A retried
        # create_remediation_proposal call for the SAME run_id uses the
        # SAME idempotency_key, so it safely converges on the SAME
        # proposal rather than creating a duplicate (Phase 8 §PROPOSAL
        # IDEMPOTENCY).

        return {
            "remediation_proposal_id": str(proposal.id),
            "remediation_action_type": proposal.action_type,
            "remediation_target": proposal.target,
            "remediation_status": "pending_approval",
            "current_node": "propose_remediation",
            "completed_nodes": ["propose_remediation"],
            "updated_at": now,
        }

    async def await_human_approval(state: AgentGraphState) -> dict:
        """Phase 8 §LANGGRAPH HUMAN INTERRUPT. The ONLY thing this
        node does before calling `interrupt(...)` is read already-set
        state fields -- no side effect, no external call -- because
        LangGraph RE-EXECUTES this node's body from the top on every
        resume attempt (confirmed directly against the installed,
        pinned langgraph==1.2.15 source before this was written); the
        interrupt payload is safe to recompute every time.

        The value `interrupt()` returns on resume is NEVER a
        caller-supplied value -- it is the Command(resume=...) payload
        api/agent_runs.py::resume_agent_run builds EXCLUSIVELY from
        control-plane's own trusted, persisted decision record (Phase
        8 §HUMAN DECISION SOURCE OF TRUTH). This node has no way to
        tell the difference between a real human decision and a faked
        one -- that guarantee is enforced entirely by the API layer,
        never here; this node simply trusts whatever decision value it
        is resumed with, by design.
        """
        payload = {
            "proposal_id": state.get("remediation_proposal_id"),
            "action_type": state.get("remediation_action_type"),
            "target": state.get("remediation_target"),
            "reason": "human approval required before executing this remediation action",
            "risk": "low",
        }
        decision = interrupt(payload)
        decision_value = decision.get("decision") if isinstance(decision, dict) else None

        now = _now_iso()
        if decision_value == "approved":
            return {
                "approval_decision": "approved",
                "remediation_status": "approved",
                "current_node": "await_human_approval",
                "completed_nodes": ["await_human_approval"],
                "updated_at": now,
            }
        return {
            "approval_decision": "rejected",
            "remediation_status": "rejected",
            "current_node": "await_human_approval",
            "completed_nodes": ["await_human_approval"],
            "updated_at": now,
        }

    async def execute_remediation(state: AgentGraphState) -> dict:
        """Only ever reached after a REAL, trusted 'approved' decision
        (see route_after_await_human_approval below). tool-gateway
        independently re-verifies control-plane's own proposal state
        before doing anything at all -- this node's own call here
        carries nothing but `proposal_id` (Phase 8 §NO CALLER-SUPPLIED
        EXECUTION TARGET)."""
        proposal_id = state.get("remediation_proposal_id")
        now = _now_iso()
        assert tool_gateway_client is not None  # unreachable otherwise -- see route_after_await_human_approval

        try:
            result = await tool_gateway_client.execute(proposal_id)
        except ToolGatewayRefusedError as exc:
            # A definitive business-level refusal (e.g. the real
            # action or its independent post-action verification
            # genuinely did not succeed) -- recorded as a failed
            # REMEDIATION outcome, never as this agent RUN's own
            # internal failure: the run itself completed its job
            # (it tried, and tool-gateway/control-plane already
            # rolled the incident back to 'investigating' on their own
            # side -- see repositories/remediation_repository.py).
            return {
                "execution_result": {"status": "failed", "detail": _safe_detail(exc.detail, bounds.max_error_detail_chars)},
                "remediation_status": "failed",
                "current_node": "execute_remediation",
                "completed_nodes": ["execute_remediation"],
                "updated_at": now,
            }
        except ToolGatewayOutputError as exc:
            # Phase 8 correction round (finding #1): a malformed/lost/
            # otherwise-ambiguous tool-gateway response does NOT prove
            # the mutation never happened -- it may have already
            # durably succeeded or failed on control-plane's own side
            # (e.g. the response was lost in transit AFTER
            # execution/result was already recorded), or it may still
            # be genuinely in flight. Never blindly terminalized;
            # always independently reconciled first.
            return await _reconcile_ambiguous_execution(proposal_id, exc, now)
        # ToolGatewayUnavailableError deliberately NOT caught --
        # TRANSIENT/RETRYABLE: the proposal remains 'executing' on
        # control-plane's own side, so a retried resume safely retries
        # the SAME idempotent action (Phase 8 §TOOL-GATEWAY EXECUTION
        # IDEMPOTENCY).

        return {
            "execution_result": {
                "status": result.status,
                "detail": _safe_detail(result.detail, bounds.max_error_detail_chars) if result.detail else None,
            },
            "remediation_status": result.status,
            "current_node": "execute_remediation",
            "completed_nodes": ["execute_remediation"],
            "updated_at": now,
        }

    async def _reconcile_ambiguous_execution(proposal_id: str | None, exc: ToolGatewayOutputError, now: str) -> dict:
        """Phase 8 correction round (finding #1): independently
        re-derives what ACTUALLY happened from control-plane's own
        durable proposal record, rather than trusting (or blindly
        terminalizing on) tool-gateway's own ambiguous execute()
        response. Three real outcomes, never guessed:

          - control-plane durably recorded 'succeeded'/'failed' ->
            report that REAL outcome (the response was merely lost in
            transit; nothing is re-executed).
          - control-plane still reports 'approved'/'executing' -> truly
            unknown/in-flight -> raises ToolGatewayAmbiguousExecutionError
            (left UNCAUGHT, same TRANSIENT/RETRYABLE convention as every
            other dependency-outage case in this module) so this node's
            checkpoint is never committed and the thread stays resumable
            at execute_remediation.
          - anything else (pending_approval/rejected, or control-plane
            itself returning a shape/not-found error) -> this node was
            somehow reached without a real completed/in-flight
            execution on control-plane's side; classified explicitly as
            a failed remediation outcome, never silently pretending any
            action occurred.
        """
        try:
            proposal = await control_plane_client.get_remediation_proposal(proposal_id)
        except RemediationProposalNotFoundError as nf_exc:
            return {
                "status": "failed",
                "error_code": "remediation_proposal_not_found",
                "error_detail": _safe_detail(str(nf_exc), bounds.max_error_detail_chars),
                "current_node": "execute_remediation",
                "completed_nodes": ["execute_remediation"],
                "updated_at": now,
            }
        except ControlPlaneOutputError as cp_exc:
            return {
                "status": "failed",
                "error_code": "control_plane_output_invalid",
                "error_detail": _safe_detail(str(cp_exc), bounds.max_error_detail_chars),
                "current_node": "execute_remediation",
                "completed_nodes": ["execute_remediation"],
                "updated_at": now,
            }
        # ControlPlaneUnavailableError deliberately NOT caught --
        # reconciliation itself being unavailable is just as
        # transient/resumable as the original ambiguous response: the
        # proposal's real state has not been confirmed either way yet.

        if proposal.status == "succeeded":
            return {
                "execution_result": {
                    "status": "succeeded",
                    "detail": "reconciled from control-plane's durable record after an ambiguous tool-gateway response",
                },
                "remediation_status": "succeeded",
                "current_node": "execute_remediation",
                "completed_nodes": ["execute_remediation"],
                "updated_at": now,
            }
        if proposal.status == "failed":
            return {
                "execution_result": {
                    "status": "failed",
                    "detail": "reconciled from control-plane's durable record after an ambiguous tool-gateway response",
                },
                "remediation_status": "failed",
                "current_node": "execute_remediation",
                "completed_nodes": ["execute_remediation"],
                "updated_at": now,
            }
        if proposal.status in ("approved", "executing"):
            raise ToolGatewayAmbiguousExecutionError(
                f"tool-gateway execute response was ambiguous ({exc}) and control-plane proposal "
                f"{proposal_id} is still {proposal.status!r}; this agent run remains resumable"
            ) from exc

        # pending_approval/rejected here would mean this node was
        # somehow reached without a real 'approved' decision ever
        # landing durably on control-plane's side -- an inconsistent,
        # effectively unreachable state given route_after_await_human_
        # approval's own guard, but defensively classified as an
        # honest, explicit failure rather than silently pretending any
        # execution occurred.
        return {
            "execution_result": {
                "status": "failed",
                "detail": _safe_detail(
                    f"control-plane proposal is unexpectedly {proposal.status!r} after an ambiguous "
                    "tool-gateway execute response",
                    bounds.max_error_detail_chars,
                ),
            },
            "remediation_status": proposal.status,
            "current_node": "execute_remediation",
            "completed_nodes": ["execute_remediation"],
            "updated_at": now,
        }

    async def verify_recovery(state: AgentGraphState) -> dict:
        """Phase 8 correction round (finding #2): independently proves
        REAL recovery, never merely durable bookkeeping. Three
        independent facts, all re-fetched FRESH here -- never trusting
        execute_remediation's own synchronous response for any of them:

          1. control-plane's own durable proposal record genuinely says
             'succeeded' (not merely what execute_remediation's
             response claimed).
          2. tool-gateway's own authenticated, independent capability/
             precondition read reports the controlled payment fault as
             currently INACTIVE (`not precondition_met`) -- a fresh
             read, not a cached belief.
          3. that SAME fresh read reports payment-service as currently
             healthy (`target_healthy`).

        All three must hold before this node ever reports
        remediation_status="succeeded"; if any is false, recovery is
        reported exactly as it was independently observed -- never
        papered over as a success merely because the durable execution
        result said so."""
        now = _now_iso()
        proposal_id = state.get("remediation_proposal_id")
        execution_result = state.get("execution_result") or {}

        if execution_result.get("status") != "succeeded" or not proposal_id:
            return {
                "recovery_verification": {
                    "proposal_succeeded": False,
                    "fault_inactive": False,
                    "target_healthy": False,
                },
                "current_node": "verify_recovery",
                "completed_nodes": ["verify_recovery"],
                "updated_at": now,
            }

        try:
            proposal = await control_plane_client.get_remediation_proposal(proposal_id)
        except RemediationProposalNotFoundError as exc:
            return {
                "status": "failed",
                "error_code": "remediation_proposal_not_found",
                "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
                "current_node": "verify_recovery",
                "completed_nodes": ["verify_recovery"],
                "updated_at": now,
            }
        except ControlPlaneOutputError as exc:
            return {
                "status": "failed",
                "error_code": "control_plane_output_invalid",
                "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
                "current_node": "verify_recovery",
                "completed_nodes": ["verify_recovery"],
                "updated_at": now,
            }
        # ControlPlaneUnavailableError deliberately NOT caught --
        # TRANSIENT/RETRYABLE.

        proposal_succeeded = proposal.status == "succeeded"
        fault_inactive = False
        target_healthy = False

        if proposal_succeeded:
            assert tool_gateway_client is not None  # unreachable otherwise -- execute_remediation always requires one
            # Phase 12B-D: a SECOND, independent fresh verification
            # (beyond tool-gateway's own executor-side recovery check
            # at execution time, Gate 7) -- the same defense-in-depth
            # "verify again, independently, from a different vantage
            # point" discipline Phase 8 already established for the
            # payment action.
            try:
                if proposal.action_type == K8S_REMEDIATION_ACTION_TYPE:
                    k8s_capability = await tool_gateway_client.get_kubernetes_capability()
                    # Correction round (Issue 5): the absence of a
                    # confirmed targeted failure reason does NOT, by
                    # itself, establish a healthy Deployment -- it could
                    # be Pending/scaling/zero-ready-replicas for an
                    # entirely unrelated reason. `fault_inactive` here
                    # additionally requires the SAME target identity
                    # (target/cluster/deployment_uid) this proposal was
                    # actually created and executed against -- a
                    # recreated Deployment during/after execution must
                    # never be silently attributed a recovery it never
                    # demonstrated. `target_healthy` requires genuine,
                    # freshly-observed readiness/availability evidence
                    # (observedGeneration caught up, every replica ready
                    # AND available, the Available condition true) --
                    # never label a resource fully recovered just
                    # because its targeted failure reason disappeared.
                    identity_matches = (
                        k8s_capability.target == proposal.target
                        and k8s_capability.target_cluster == proposal.target_cluster
                        and bool(k8s_capability.deployment_uid)
                        and k8s_capability.deployment_uid == proposal.expected_resource_uid
                    )
                    fault_inactive = identity_matches and not k8s_capability.precondition_met
                    fully_ready = (
                        k8s_capability.generation_caught_up
                        and k8s_capability.available
                        and k8s_capability.replicas > 0
                        and k8s_capability.ready_replicas == k8s_capability.replicas
                        and k8s_capability.available_replicas == k8s_capability.replicas
                    )
                    target_healthy = fault_inactive and fully_ready
                else:
                    capability = await tool_gateway_client.get_capability()
                    fault_inactive = not capability.precondition_met
                    target_healthy = capability.target_healthy
            except ToolGatewayOutputError as exc:
                return {
                    "status": "failed",
                    "error_code": "tool_gateway_output_invalid",
                    "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
                    "current_node": "verify_recovery",
                    "completed_nodes": ["verify_recovery"],
                    "updated_at": now,
                }
            # ToolGatewayUnavailableError deliberately NOT caught --
            # TRANSIENT/RETRYABLE: a temporary outage while verifying
            # recovery does not prove recovery failed; a retried resume
            # safely re-attempts this SAME read-only check.

        recovery_confirmed = proposal_succeeded and fault_inactive and target_healthy

        return {
            "recovery_verification": {
                "proposal_succeeded": proposal_succeeded,
                "fault_inactive": fault_inactive,
                "target_healthy": target_healthy,
            },
            "remediation_status": "succeeded" if recovery_confirmed else "failed",
            "current_node": "verify_recovery",
            "completed_nodes": ["verify_recovery"],
            "updated_at": now,
        }

    return (
        load_incident,
        run_investigation,
        evaluate_investigation,
        propose_remediation,
        await_human_approval,
        execute_remediation,
        verify_recovery,
        finalize,
    )


async def _propose_kubernetes_remediation(
    state: AgentGraphState, tool_gateway_client, control_plane_client, bounds: RuntimeBounds, now: str, not_applicable: dict
) -> dict:
    """Phase 12B-D §GATE 4: the Kubernetes analogue of
    propose_remediation's payment branch -- same structure, same
    "never trust a hypothesis, only a fresh independent read" rule.

    Correction round (Issue 1): a fresh tool-gateway capability alone
    is NOT sufficient authorization -- that only proves "the
    allowlisted Deployment is CURRENTLY failing somewhere", never that
    THIS incident concerns that specific Deployment/cluster/namespace.
    This function additionally resolves the incident's OWN trusted,
    persisted Kubernetes evidence (control-plane's GET /api/v1/incidents/
    {id}/kubernetes-evidence -- never LLM text, never a title
    substring, never mere temporal proximity) and requires a
    demonstrable identity/ownership relationship between that evidence
    and the allowlisted target before ever creating a proposal."""
    incident_id = str(state["incident_id"])
    try:
        evidence = await control_plane_client.get_kubernetes_incident_evidence(incident_id)
    except ControlPlaneOutputError as exc:
        return {
            "status": "failed",
            "error_code": "control_plane_output_invalid",
            "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
            "current_node": "propose_remediation",
            "completed_nodes": ["propose_remediation"],
            "updated_at": now,
        }
    # ControlPlaneUnavailableError deliberately NOT caught --
    # TRANSIENT/RETRYABLE, same reasoning as every other dependency
    # call here.

    if evidence is None:
        # This incident has no recorded Kubernetes evidence at all
        # (e.g. it is not actually kubernetes-sourced, or has no
        # history yet) -- never a reason to authorize anything.
        return not_applicable

    if (
        evidence.cluster != K8S_REMEDIATION_TARGET_CLUSTER
        or evidence.namespace != K8S_REMEDIATION_TARGET_NAMESPACE
        or evidence.detector_id not in _K8S_CONFIRMED_FAILURE_DETECTOR_IDS
        or evidence.result != "confirmed"
        or evidence.collection_completeness != "complete"
    ):
        # Wrong cluster, wrong namespace, a detector class that is
        # never sufficient to authorize a restart (e.g. oom_killed),
        # an unconfirmed (insufficient_evidence) result, or a partial
        # collection -- never authorized on incomplete/weaker evidence.
        return not_applicable

    evidence_age = datetime.now(UTC) - evidence.collected_at
    if evidence_age > K8S_EVIDENCE_MAX_STALENESS:
        # A previous, stale observation must never establish a CURRENT
        # failure -- this incident's own evidence may be real, but it
        # is too old to trust right now.
        return not_applicable

    # Demonstrable identity/ownership relationship to the ONE
    # allowlisted Deployment -- never inferred from LLM text or a
    # title substring.
    if evidence.resource_kind == "Deployment":
        if evidence.resource_name != K8S_REMEDIATION_TARGET_DEPLOYMENT_NAME:
            return not_applicable
    elif evidence.resource_kind == "Pod":
        if not evidence.resource_uid:
            # A Pod-level finding with no resource_uid at all can never
            # demonstrate ownership -- missing UID is NOT treated as
            # equivalent to a match.
            return not_applicable
    else:
        return not_applicable

    try:
        capability = await tool_gateway_client.get_kubernetes_capability()
    except ToolGatewayOutputError as exc:
        return {
            "status": "failed",
            "error_code": "tool_gateway_output_invalid",
            "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
            "current_node": "propose_remediation",
            "completed_nodes": ["propose_remediation"],
            "updated_at": now,
        }
    # ToolGatewayUnavailableError deliberately NOT caught -- TRANSIENT/
    # RETRYABLE, same reasoning as every other dependency call here.

    if not (
        capability.action_type == K8S_REMEDIATION_ACTION_TYPE
        and capability.target == K8S_REMEDIATION_TARGET
        and capability.target_cluster == K8S_REMEDIATION_TARGET_CLUSTER
        and capability.precondition_met
        and capability.deployment_uid
    ):
        return not_applicable

    if evidence.resource_kind == "Pod" and evidence.resource_uid not in capability.failing_pod_uids:
        # The SPECIFIC pod this incident's own evidence names is not
        # among the pods tool-gateway CURRENTLY, independently observes
        # as both owned by the allowlisted Deployment AND actually
        # failing -- this incident is not demonstrably about the
        # allowlisted target's current state (it may be stale, about a
        # since-recreated pod, or genuinely unrelated). Never
        # authorized on "some pod somewhere is failing".
        return not_applicable

    # Correction round (Issue 3): Deployment-kind evidence must be
    # bound to tool-gateway's own freshly-read deployment_uid, exactly
    # like Pod-kind evidence is bound to failing_pod_uids above -- a
    # bare resource_name match is NOT sufficient (a Deployment can be
    # deleted and recreated with the SAME name but a DIFFERENT UID).
    # `evidence.resource_uid != capability.deployment_uid` is also
    # exactly how a missing/None evidence UID fails closed here: None
    # can never equal capability.deployment_uid (already proven
    # non-empty by the check above).
    if evidence.resource_kind == "Deployment" and evidence.resource_uid != capability.deployment_uid:
        return not_applicable

    evidence_ids = _collect_supporting_evidence_ids(state.get("investigation_report"))
    context_ids = _collect_supporting_context_ids(state.get("investigation_report"))
    reason = _safe_detail(
        f"deterministic policy match: kubernetes-sourced incident with its own trusted evidence "
        f"(detector={evidence.detector_id!r}, resource={evidence.resource_kind}/{evidence.namespace}/"
        f"{evidence.resource_name}) demonstrably tied to the allowlisted Deployment, an existing "
        f"investigation, and tool-gateway independently confirming the same targeted failure is "
        f"CURRENTLY active with a freshly-read Deployment UID",
        bounds.max_error_detail_chars,
    )

    try:
        proposal = await control_plane_client.create_remediation_proposal(
            incident_id=state["incident_id"],
            agent_run_id=state["run_id"],
            idempotency_key=f"phase12b-k8s-proposal:{state['run_id']}",
            action_type=K8S_REMEDIATION_ACTION_TYPE,
            target=K8S_REMEDIATION_TARGET,
            target_cluster=K8S_REMEDIATION_TARGET_CLUSTER,
            expected_resource_uid=capability.deployment_uid,
            reason=reason,
            supporting_evidence_ids=evidence_ids,
            supporting_context_ids=context_ids,
        )
    except RemediationProposalConflictError as exc:
        return {
            "status": "failed",
            "error_code": "remediation_proposal_conflict",
            "error_detail": _safe_detail(str(exc), bounds.max_error_detail_chars),
            "current_node": "propose_remediation",
            "completed_nodes": ["propose_remediation"],
            "updated_at": now,
        }
    # RemediationProposalCreateAmbiguousError / ControlPlaneUnavailableError
    # deliberately NOT caught -- same TRANSIENT/RETRYABLE convention as
    # the payment branch immediately above in propose_remediation.

    return {
        "remediation_proposal_id": str(proposal.id),
        "remediation_action_type": proposal.action_type,
        "remediation_target": proposal.target,
        "remediation_status": "pending_approval",
        "current_node": "propose_remediation",
        "completed_nodes": ["propose_remediation"],
        "updated_at": now,
    }


def classify_investigation(report: dict) -> str:
    """Deterministic, orchestration-level assessment (Phase 7 node 3) --
    NEVER a second LLM call, never invented certainty, and NEVER a
    claim that any root cause has been CONFIRMED. This is orchestration
    metadata only; it does not and must not alter investigator-service's
    own Phase 5/6 epistemic boundary between a confirmed `observation`
    (evidence-grounded fact) and an unconfirmed `hypothesis` (plausible,
    never proven) -- see docs/architecture/phase-5-ai-investigator.md.

    Phase 7 correction round (finding #12): the prior vocabulary
    ("conclusive") and logic considered any evidence-backed hypothesis
    equally "conclusive" regardless of the model's own declared
    `confidence` -- so a hypothesis the model itself flagged "low"
    confidence could still be labeled in a way a caller could easily
    misread as "root cause confirmed," merely because telemetry sources
    happened to be reachable. Renamed and corrected:

      - "inconclusive": the model produced no observations AND no
        hypotheses at all -- nothing to evaluate.
      - "well_supported": at least one hypothesis is backed by real
        current-incident evidence (a non-empty supporting_evidence_ids
        -- Phase 6's own validation already guarantees any SURVIVING
        hypothesis has this) AND the model itself declared that
        hypothesis "high" confidence (never "low" or "medium" -- this
        is the "at minimum" bar Phase 7's own correction round
        requires), AND the model reported no missing evidence, AND no
        telemetry source was "unavailable", AND the Phase 6 retrieval
        step itself was not "unavailable". This still only means
        "well supported by available evidence, per the model's own
        stated confidence" -- never "confirmed."
      - "partial": everything in between -- the common case: some
        real signal exists (an observation, or a hypothesis that is
        evidence-backed but not high-confidence, or evidence-backed and
        high-confidence but with an honestly-flagged gap), but the
        well_supported bar above is not met.
    """
    observations = report.get("observations", [])
    hypotheses = report.get("hypotheses", [])
    missing_evidence = report.get("missing_evidence", [])
    source_outcomes = report.get("source_outcomes", [])
    retrieval_context = report.get("retrieval_context") or {}

    if not observations and not hypotheses:
        return "inconclusive"

    has_high_confidence_evidence_backed_hypothesis = any(
        h.get("supporting_evidence_ids") and h.get("confidence") == "high" for h in hypotheses
    )
    any_source_unavailable = any(o.get("status") == "unavailable" for o in source_outcomes)
    retrieval_unavailable = retrieval_context.get("outcome") == "unavailable"

    if (
        has_high_confidence_evidence_backed_hypothesis
        and not missing_evidence
        and not any_source_unavailable
        and not retrieval_unavailable
    ):
        return "well_supported"

    return "partial"


def _collect_supporting_evidence_ids(report: dict | None) -> list[str]:
    """Deterministic, structural extraction only -- never parses or
    reasons about any `statement` prose. Deduplicated and capped at
    MAX_SUPPORTING_IDS -- mirrors V6's own database-level ceiling.

    Phase 8 correction round (finding #5): the deterministic stub
    provider (and, in general, any report whose real support lives in
    its OBSERVATIONS rather than a hypothesis) can produce a report
    with cited evidence but NO hypotheses at all -- a prior version of
    this function only ever looked at
    `hypothesis.supporting_evidence_ids`, so such a report would
    produce an empty, provenance-less proposal even though the
    investigation genuinely cited real evidence. Now collects BOTH
    `observation.evidence_ids` (every observation's own cited evidence
    -- confirmed facts, Phase 5/6's own epistemic floor) AND
    `hypothesis.supporting_evidence_ids` -- deliberately never
    `hypothesis.conflicting_evidence_ids`, which by definition does NOT
    support this proposal's own reasoning."""
    if not report:
        return []
    ids: list[str] = []
    for observation in report.get("observations", []):
        for evidence_id in observation.get("evidence_ids", []):
            if evidence_id not in ids:
                ids.append(evidence_id)
            if len(ids) >= MAX_SUPPORTING_IDS:
                return ids
    for hypothesis in report.get("hypotheses", []):
        for evidence_id in hypothesis.get("supporting_evidence_ids", []):
            if evidence_id not in ids:
                ids.append(evidence_id)
            if len(ids) >= MAX_SUPPORTING_IDS:
                return ids
    return ids


def _collect_supporting_context_ids(report: dict | None) -> list[str]:
    """Deterministic, structural extraction only -- never the retrieved
    excerpt text itself. Deduplicated and capped at MAX_SUPPORTING_IDS.

    Phase 8 correction round (finding #5): a prior version of this
    function collected EVERY item control-plane's own Phase 6 retrieval
    step returned (`retrieval_context.{knowledge,historical_incidents}`)
    -- that is "everything retrieved", not "supporting context"; some
    retrieved context can be irrelevant or even conflicting. Now
    collects ONLY `hypothesis.supporting_context_ids` -- the model's own
    declared judgement of which retrieved items actually support its
    reasoning -- and deliberately never
    `hypothesis.conflicting_context_ids` or any unreferenced retrieval
    item."""
    if not report:
        return []
    ids: list[str] = []
    for hypothesis in report.get("hypotheses", []):
        for context_id in hypothesis.get("supporting_context_ids", []):
            if context_id not in ids:
                ids.append(context_id)
            if len(ids) >= MAX_SUPPORTING_IDS:
                return ids
    return ids


def route_after_load_incident(state: AgentGraphState) -> str:
    return "finalize" if state.get("status") == "failed" else "run_investigation"


def route_after_run_investigation(state: AgentGraphState) -> str:
    return "finalize" if state.get("status") == "failed" else "evaluate_investigation"


def route_after_propose_remediation(state: AgentGraphState) -> str:
    """Phase 8: a proposal was actually created (remediation_proposal_id
    is set) -> wait for a real human decision. No policy match (or a
    terminal error -- status=="failed") -> finalize directly; a run
    with nothing to remediate never touches await_human_approval at
    all."""
    if state.get("status") == "failed":
        return "finalize"
    return "await_human_approval" if state.get("remediation_proposal_id") else "finalize"


def route_after_await_human_approval(state: AgentGraphState) -> str:
    """Phase 8 §APPROVAL REJECTION PATH / §APPROVAL APPROVED PATH:
    only a REAL, trusted 'approved' decision (resumed via
    api/agent_runs.py from control-plane's own durable record) ever
    reaches execute_remediation. Anything else (rejected, or an
    unexpected/malformed decision value) finalizes directly -- no
    tool-gateway call, no payment-service call, no incident
    transition."""
    return "execute_remediation" if state.get("approval_decision") == "approved" else "finalize"


def route_after_execute_remediation(state: AgentGraphState) -> str:
    return "finalize" if state.get("status") == "failed" else "verify_recovery"


# Re-exported so callers (and tests) don't need to reach into
# clients/domain modules just to validate a report shape.
__all__ = [
    "AgentGraphState",
    "IncidentSnapshot",
    "InvestigationReport",
    "REMEDIATION_ACTION_TYPE",
    "REMEDIATION_TARGET",
    "build_nodes",
    "classify_investigation",
    "route_after_await_human_approval",
    "route_after_execute_remediation",
    "route_after_load_incident",
    "route_after_propose_remediation",
    "route_after_run_investigation",
]
