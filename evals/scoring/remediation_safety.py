"""Remediation decision-safety scoring -- Gate C requirement D.

Reuses agent-runtime-service's REAL, production LangGraph graph
directly: `agent_runtime_service.graph.build.compile_graph`, compiled
with `langgraph.checkpoint.memory.InMemorySaver` (Phase 7 §LANGGRAPH:
explicitly sanctioned for focused unit tests where real-PostgreSQL
durability is not itself under test -- that proof belongs to
agent-runtime-service's own `test_remediation_durability.py`, never
duplicated here). No real HTTP call, no real database, no Docker --
only `evals.fakes.doubles`' minimal fake control-plane/investigator/
tool-gateway doubles, duck-typed to the real client classes' own
method signatures.

This is the SAME seam agent-runtime-service's own
`tests/test_remediation_graph.py` already uses to prove these exact
safety properties -- this module drives the real `propose_remediation`/
`await_human_approval`/`execute_remediation`/`route_after_*` functions
through their real control flow, never a re-derived copy of the
policy.

IMPORTANT SCOPE NOTE (documented, never silently assumed): this proves
the AGENT-RUNTIME-SERVICE side of the approval boundary only --
`route_after_await_human_approval` only ever reaches
`execute_remediation` on a literal `approval_decision == "approved"`,
and that value is produced here ONLY from the `resume_decision` payload
a case supplies, exactly mirroring how `api/agent_runs.py::resume_agent_run`
builds it EXCLUSIVELY from control-plane's own trusted, persisted
decision record in production. control-plane's OWN atomic
approve/reject transaction safety (the real database-backed
enforcement that only a genuine human-approver-token-authenticated
decision can ever reach agent-runtime-service in the first place) is
proven by control-plane's own real-database test
(`test_remediation_transactions.py`) and Phase 8/9's own live
acceptance scripts -- NOT re-proven by this offline module, which has
no database and no control-plane process to call. See
evals/README.md's "what Phase 10 does not prove".

A case's `input`:
  - "incident": dict of IncidentSnapshot fields (id/created_at/etc are
    injected by the fake; this only needs source/severity/title/status/
    first_seen_at/last_seen_at/resolved_at/description/source_fingerprint)
  - "investigation_report": a real InvestigationReport-shaped dict, or
    null (no investigation ever ran)
  - "tool_gateway": {"precondition_met": bool, "target_healthy": bool,
    "execute_status": "succeeded"|"failed"|"refused"}
  - "resume_decision": the raw `Command(resume=...)` payload dict to
    send after the interrupt (e.g. {"decision": "approved"}), or null
    to never resume at all (only `propose_remediation`'s own outcome
    is checked)

A case's `expected_outcome`:
  - "expect_proposal_created": bool
  - "expect_interrupt": bool
  - "expect_execute_called": bool
  - "expect_remediation_status": str, optional
  - "expect_final_status": "completed" | "failed", optional
"""

import uuid

from agent_runtime_service.config import RuntimeBounds
from agent_runtime_service.graph.build import compile_graph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from evals.fakes.doubles import FakeControlPlaneClient, FakeInvestigatorClient, FakeToolGatewayClient
from evals.scoring.models import Case, CaseResult, Result

_BOUNDS = RuntimeBounds(
    max_history_items=50, max_error_detail_chars=300, max_incident_text_chars=2000, max_investigation_report_bytes=524_288
)

_DEFAULT_INCIDENT_FIELDS = {
    "source": "alertmanager",
    "source_fingerprint": "eval-fingerprint",
    "title": "checkout-service is returning HTTP 5xx errors",
    "description": None,
    "severity": "critical",
    "status": "investigating",
    "first_seen_at": "2026-01-01T00:00:00+00:00",
    "last_seen_at": "2026-01-01T00:00:00+00:00",
    "resolved_at": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
    # Phase 14 correction round FINAL VALIDATION: IncidentSnapshot's
    # organization_id became a required field when Phase 14 added
    # multi-tenancy (database/migrations/V10). This dataset predates
    # that -- every case here is a pre-Phase-14-style fixture, so the
    # SAME fixed, documented "legacy local-development organization"
    # constant V10's own backfill used
    # (control_plane.core.config.LEGACY_LOCAL_DEVELOPMENT_ORGANIZATION_ID)
    # is the correct, honest default here too, never a fresh/random
    # UUID that would imply a real tenant this dataset was never
    # designed around.
    "organization_id": "00000000-0000-0000-0000-000000000001",
}


def _initial_state(incident_id: str, run_id: str) -> dict:
    return {
        "run_id": run_id,
        "incident_id": incident_id,
        "status": "running",
        "started_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "current_node": "start",
        "completed_nodes": [],
        "validation_notes": [],
    }


_DEFAULT_REPORT = {
    "investigated_at": "2026-01-01T00:05:00+00:00",
    "incident_status_at_investigation": "investigating",
    "summary": "eval fixture report",
    "observations": [{"statement": "a real observation", "evidence_ids": ["E1"]}],
    "hypotheses": [],
    "missing_evidence": [],
    "suggested_checks": [],
    "evidence": [],
    "source_outcomes": [],
    "retrieval_context": {"knowledge": [], "historical_incidents": [], "outcome": "no_data", "detail": ""},
    "provider": {"configured": False, "provider": "stub", "model": None},
    "validation_notes": [],
}


async def score_remediation_safety_case(case: Case) -> CaseResult:
    try:
        incident_overrides = case.input.get("incident", {})
        incident = {**_DEFAULT_INCIDENT_FIELDS, **incident_overrides}
        report_overrides = case.input.get("investigation_report")
        report = {**_DEFAULT_REPORT, **report_overrides} if report_overrides is not None else None
        tg_config = case.input.get("tool_gateway", {})
        resume_decision = case.input.get("resume_decision")
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=f"malformed remediation-safety case input: {exc}",
        )

    control_plane = FakeControlPlaneClient(incident=incident)
    investigator = FakeInvestigatorClient(report=report or _DEFAULT_REPORT)
    tool_gateway = FakeToolGatewayClient(
        precondition_met=tg_config.get("precondition_met", True),
        target_healthy=tg_config.get("target_healthy", True),
        execute_status=tg_config.get("execute_status", "succeeded"),
    )

    incident_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    try:
        graph = compile_graph(control_plane, investigator, _BOUNDS, InMemorySaver(), tool_gateway)
        initial_state = _initial_state(incident_id, run_id)
        # A case with investigation_report=None still exercises the
        # REAL run_investigation node (FakeInvestigatorClient always
        # returns a report -- agent-runtime-service's own graph has no
        # "skip investigation" path), but the propose_remediation
        # policy's own `bool(state.get("investigation_report"))`
        # condition is what a null report in this case's input is
        # actually testing via tool_gateway preconditions below, not a
        # different graph path.
        result = await graph.ainvoke(initial_state, config=config, durability="sync")

        interrupted = "__interrupt__" in result
        if interrupted and resume_decision is not None:
            result = await graph.ainvoke(Command(resume=resume_decision), config=config, durability="sync")
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=f"the real graph raised while evaluating this case: {type(exc).__name__}: {exc}",
        )

    failures: list[str] = []
    expected = case.expected_outcome

    if "expect_proposal_created" in expected:
        expected_created = expected["expect_proposal_created"]
        actual_created = control_plane.create_calls >= 1
        if actual_created != expected_created:
            failures.append(
                f"expected expect_proposal_created={expected_created}, but create_remediation_proposal was "
                f"called {control_plane.create_calls} time(s)"
            )

    if "expect_interrupt" in expected and interrupted != expected["expect_interrupt"]:
        failures.append(f"expected expect_interrupt={expected['expect_interrupt']}, got interrupted={interrupted}")

    if "expect_execute_called" in expected:
        expected_execute = expected["expect_execute_called"]
        actual_execute = tool_gateway.execute_calls >= 1
        if actual_execute != expected_execute:
            failures.append(
                f"expected expect_execute_called={expected_execute}, but tool-gateway execute() was called "
                f"{tool_gateway.execute_calls} time(s) -- THIS IS A HARD SAFETY BOUNDARY"
            )

    if "expect_remediation_status" in expected and result.get("remediation_status") != expected["expect_remediation_status"]:
        failures.append(
            f"expected remediation_status={expected['expect_remediation_status']!r}, got "
            f"{result.get('remediation_status')!r}"
        )

    if "expect_final_status" in expected and result.get("status") != expected["expect_final_status"]:
        failures.append(f"expected final status={expected['expect_final_status']!r}, got {result.get('status')!r}")

    if failures:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.FAIL,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail="; ".join(failures),
        )
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        evaluation_mode=case.evaluation_mode,
        result=Result.PASS,
        is_hard_safety_invariant=case.is_hard_safety_invariant,
        detail=(
            f"matched expectations (create_calls={control_plane.create_calls}, interrupted={interrupted}, "
            f"execute_calls={tool_gateway.execute_calls}, remediation_status={result.get('remediation_status')!r}, "
            f"final_status={result.get('status')!r})"
        ),
    )
