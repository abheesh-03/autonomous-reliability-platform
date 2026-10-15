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
from datetime import UTC, datetime

from agent_runtime_service.clients.control_plane import (
    ControlPlaneClient,
    ControlPlaneOutputError,
    IncidentNotFoundError,
)
from agent_runtime_service.clients.investigator import InvestigatorClient, InvestigatorOutputError
from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.domain.incident_snapshot import IncidentSnapshot
from agent_runtime_service.domain.investigation import InvestigationReport
from agent_runtime_service.graph.state import AgentGraphState
from agent_runtime_service.text_safety import bound_and_redact, hard_bound

logger = logging.getLogger("agent_runtime_service.graph.nodes")


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
):
    """Returns the four node callables, each a plain
    `async def (state) -> dict` LangGraph node function."""

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

    return load_incident, run_investigation, evaluate_investigation, finalize


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


def route_after_load_incident(state: AgentGraphState) -> str:
    return "finalize" if state.get("status") == "failed" else "run_investigation"


def route_after_run_investigation(state: AgentGraphState) -> str:
    return "finalize" if state.get("status") == "failed" else "evaluate_investigation"


# Re-exported so callers (and tests) don't need to reach into
# clients/domain modules just to validate a report shape.
__all__ = [
    "AgentGraphState",
    "IncidentSnapshot",
    "InvestigationReport",
    "build_nodes",
    "classify_investigation",
    "route_after_load_incident",
    "route_after_run_investigation",
]
