"""Phase 12B-D correction round (Issue 6B): an explicit, OPT-IN,
authenticated delivery path that publishes Phase 12A's own confirmed
Kubernetes findings into control-plane's durable incident store (POST
/internal/v1/kubernetes/findings).

This is deliberately NOT wired into `python -m detectors analyze` by
default -- it only runs when a caller explicitly passes
`--publish-to-control-plane` (see cli/commands.py). A single
`publish()` call here is exactly ONE bounded, point-in-time HTTP
round-trip PER finding; there is no retry loop, no polling, no
background task, and no scheduler anywhere in this module. This
process still has no daemon mode at all (see cli/commands.py's own
module docstring) -- running this repeatedly (e.g. from an external
cron job an operator sets up) is what "continuous monitoring" would
require, and that remains entirely the operator's own, separately
visible decision; this module itself never claims or implies ongoing
monitoring.

Idempotency/retry semantics are NOT reimplemented here -- they already
live in control-plane's own ingestion service
(control_plane.ingestion.kubernetes_service), which is itself
idempotent per (fingerprint, collected_at). A publish failure for one
finding (network error, non-2xx response) is reported honestly and
never silently retried in a loop, and never fabricates a durable
incident id for a finding that was not actually accepted -- see
PublishOutcome.failed's own docstring.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx

from detectors.schemas.kubernetes import CollectionOutcome, CollectionResult, K8sDetectionFinding, K8sDetectionResult

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class PublishResult:
    """The outcome of publishing ONE finding -- never aggregated into
    a single boolean; a caller can always see exactly which findings
    were accepted, ignored, or failed, and why."""

    detector_id: str
    resource_kind: str
    namespace: str
    resource_name: str
    # "created" | "updated" | "ignored" on a real 2xx acceptance;
    # "failed" when the finding was never durably accepted by
    # control-plane at all -- see the module docstring: a failure here
    # NEVER invents a durable incident id.
    outcome: str
    incident_id: str | None = None
    detail: str = ""


def _collection_completeness_for(resource_kind: str, k8s_collection_results: list[CollectionResult]) -> str:
    """Maps this run's own CollectionResult outcomes onto the
    ingestion schema's `collection_completeness` vocabulary --
    "partial" if the relevant underlying collection for this
    resource_kind was itself PARTIAL (Phase 12A pagination/malformed-
    item correction round), "complete" otherwise. Never guesses; a
    resource_kind this run never collected at all (should not happen
    given how this module is called, but handled defensively) is
    conservatively reported as "partial" -- never a false "complete"
    claim."""
    relevant_kind = "Pod" if resource_kind == "Pod" else "Deployment"
    matching = [cr for cr in k8s_collection_results if cr.resource_kind == relevant_kind]
    if not matching:
        return "partial"
    return "complete" if all(cr.outcome in (CollectionOutcome.SUCCESS, CollectionOutcome.EMPTY) for cr in matching) else "partial"


def _finding_to_request_body(
    finding: K8sDetectionFinding, *, cluster: str, collection_completeness: str, collected_at: datetime
) -> dict:
    return {
        "cluster": cluster,
        "namespace": finding.namespace,
        "resource_kind": finding.resource_kind,
        "resource_name": finding.resource_name,
        "resource_uid": finding.resource_uid,
        "detector_id": finding.detector_id,
        "result": finding.result.value,
        "collection_completeness": collection_completeness,
        "collected_at": collected_at.isoformat(),
        "decision_rationale": finding.decision_rationale,
        "evidence": dict(finding.evidence),
        "supporting_event_reasons": list(finding.supporting_event_reasons),
    }


async def publish_kubernetes_findings(
    k8s_findings: list[K8sDetectionFinding],
    k8s_collection_results: list[CollectionResult],
    *,
    cluster: str,
    collected_at: datetime,
    control_plane_url: str,
    ingestion_token: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[PublishResult]:
    """Publishes every finding in `k8s_findings` (both CONFIRMED and
    INSUFFICIENT_EVIDENCE -- Phase 12A's own pipeline already never
    produces a finding object for a genuinely healthy resource, so
    there is nothing to filter out here; a weaker INSUFFICIENT_EVIDENCE
    signal is still real, structured evidence worth a durable record,
    mapped to a correspondingly weaker 'warning' severity by
    control-plane's own ingestion/kubernetes_mapping.py).

    One bounded HTTP POST per finding, sequentially -- never
    concurrent/fire-and-forget, so a caller can correlate exactly which
    network/auth error applies to which finding. Returns a
    PublishResult per finding; never raises for an individual finding's
    network/HTTP failure (a bounded per-finding try/except), so one bad
    finding can never abort publishing the rest."""
    results: list[PublishResult] = []
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        for finding in k8s_findings:
            completeness = _collection_completeness_for(finding.resource_kind, k8s_collection_results)
            body = _finding_to_request_body(finding, cluster=cluster, collection_completeness=completeness, collected_at=collected_at)
            try:
                resp = await client.post(
                    f"{control_plane_url.rstrip('/')}/internal/v1/kubernetes/findings",
                    headers={"Authorization": f"Bearer {ingestion_token}"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                results.append(
                    PublishResult(
                        detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                        namespace=finding.namespace, resource_name=finding.resource_name,
                        outcome="failed", detail=f"could not reach control-plane: {type(exc).__name__}",
                    )
                )
                continue

            if resp.status_code != 201:
                # Never a durable incident id on anything other than
                # the documented 201 -- a 4xx/5xx/unexpected response
                # is reported as a failure, not silently treated as
                # "probably fine".
                detail = f"control-plane returned HTTP {resp.status_code}"
                try:
                    body_json = resp.json()
                    if isinstance(body_json, dict) and "detail" in body_json:
                        detail += f": {body_json['detail']}"
                except ValueError:
                    pass
                results.append(
                    PublishResult(
                        detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                        namespace=finding.namespace, resource_name=finding.resource_name,
                        outcome="failed", detail=detail,
                    )
                )
                continue

            try:
                response_body = resp.json()
                incident_id = response_body["incident_id"]
                outcome = response_body["outcome"]
            except (ValueError, KeyError):
                results.append(
                    PublishResult(
                        detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                        namespace=finding.namespace, resource_name=finding.resource_name,
                        outcome="failed", detail="control-plane's 201 response did not match the expected shape",
                    )
                )
                continue

            results.append(
                PublishResult(
                    detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                    namespace=finding.namespace, resource_name=finding.resource_name,
                    outcome=outcome, incident_id=incident_id,
                )
            )
    return results
