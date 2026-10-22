"""Phase 13, Gate 3/4: an explicit, OPT-IN, authenticated delivery path
that publishes the AWS observer's own confirmed findings into
control-plane's durable incident store (POST /internal/v1/aws/findings)
-- mirrors `detectors.kubernetes.publisher`'s own structure and
discipline exactly, including its NON-daemon, NON-retrying,
one-bounded-HTTP-call-per-finding semantics. See that module's
docstring for the full set of guarantees this module equally provides;
not repeated here verbatim.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx

from detectors.schemas.aws import AwsCollectionOutcome, AwsCollectionResult, AwsDetectionFinding

DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class AwsPublishResult:
    detector_id: str
    resource_kind: str
    resource_id: str
    outcome: str  # "created" | "updated" | "ignored" | "failed" -- see kubernetes publisher's own docstring
    incident_id: str | None = None
    detail: str = ""


def _collection_completeness_for(resource_kind: str, collection_results: list[AwsCollectionResult]) -> str:
    matching = [cr for cr in collection_results if cr.resource_kind == resource_kind]
    if not matching:
        return "partial"
    return "complete" if all(cr.outcome in (AwsCollectionOutcome.SUCCESS, AwsCollectionOutcome.EMPTY) for cr in matching) else "partial"


def _finding_to_request_body(finding: AwsDetectionFinding, *, collection_completeness: str, collected_at: datetime) -> dict:
    return {
        "account_id": finding.account_id,
        "region": finding.region,
        "resource_kind": finding.resource_kind,
        "resource_id": finding.resource_id,
        "resource_arn": finding.resource_arn,
        "detector_id": finding.detector_id,
        "result": finding.result.value,
        "collection_completeness": collection_completeness,
        "collected_at": collected_at.isoformat(),
        "decision_rationale": finding.decision_rationale,
        "evidence": dict(finding.evidence),
        "supporting_change_events": list(finding.supporting_change_events),
    }


async def publish_aws_findings(
    aws_findings: list[AwsDetectionFinding],
    collection_results: list[AwsCollectionResult],
    *,
    collected_at: datetime,
    control_plane_url: str,
    ingestion_token: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[AwsPublishResult]:
    """One bounded HTTP POST per finding, sequentially -- never
    concurrent/fire-and-forget. Returns an AwsPublishResult per finding;
    never raises for an individual finding's network/HTTP failure."""
    results: list[AwsPublishResult] = []
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        for finding in aws_findings:
            completeness = _collection_completeness_for(finding.resource_kind, collection_results)
            body = _finding_to_request_body(finding, collection_completeness=completeness, collected_at=collected_at)
            try:
                resp = await client.post(
                    f"{control_plane_url.rstrip('/')}/internal/v1/aws/findings",
                    headers={"Authorization": f"Bearer {ingestion_token}"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                results.append(
                    AwsPublishResult(
                        detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                        resource_id=finding.resource_id, outcome="failed",
                        detail=f"could not reach control-plane: {type(exc).__name__}",
                    )
                )
                continue

            if resp.status_code != 201:
                detail = f"control-plane returned HTTP {resp.status_code}"
                try:
                    body_json = resp.json()
                    if isinstance(body_json, dict) and "detail" in body_json:
                        detail += f": {body_json['detail']}"
                except ValueError:
                    pass
                results.append(
                    AwsPublishResult(
                        detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                        resource_id=finding.resource_id, outcome="failed", detail=detail,
                    )
                )
                continue

            try:
                response_body = resp.json()
                incident_id = response_body["incident_id"]
                outcome = response_body["outcome"]
            except (ValueError, KeyError):
                results.append(
                    AwsPublishResult(
                        detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                        resource_id=finding.resource_id, outcome="failed",
                        detail="control-plane's 201 response did not match the expected shape",
                    )
                )
                continue

            results.append(
                AwsPublishResult(
                    detector_id=finding.detector_id, resource_kind=finding.resource_kind,
                    resource_id=finding.resource_id, outcome=outcome, incident_id=incident_id,
                )
            )
    return results
