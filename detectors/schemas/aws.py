"""Phase 13, Gate 1: the AWS observation contract.

Mirrors `detectors.schemas.kubernetes`'s own honesty discipline exactly
(Phase 12A): a collection attempt always produces one of a small,
explicit set of outcomes, and a failed/forbidden/throttled collection
must never be reported as, or silently treated as, a healthy result.
AWS adds one outcome Kubernetes never needed -- THROTTLED -- since
CloudWatch/CloudTrail/EC2/ECS APIs are genuinely rate-limited in a way
a local kind cluster's API server is not; a throttled call is neither
"the resource doesn't exist" (NOT_FOUND) nor "nothing is reachable"
(UNAVAILABLE) nor "forbidden" (FORBIDDEN) -- it is its own distinct,
honest outcome a caller must handle by backing off, never by guessing.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class AwsCollectionOutcome(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"  # the API call succeeded and genuinely returned zero items
    PARTIAL = "partial"  # some real evidence was collected and is preserved, but collection is KNOWN
    # INCOMPLETE -- e.g. a bounded page/item cap was reached while more pages existed, or a
    # subsequent page failed/was forbidden/throttled. PARTIAL must NEVER be treated as a
    # complete, healthy observation.
    MALFORMED = "malformed"  # a successful response that did not match the expected shape
    UNAVAILABLE = "unavailable"  # could not reach the AWS API at all (network/connection/credential failure)
    FORBIDDEN = "forbidden"  # the AWS API was reached, but returned AccessDenied/UnauthorizedOperation
    THROTTLED = "throttled"  # the AWS API was reached, but returned a throttling/rate-limit error
    NOT_FOUND = "not_found"  # the AWS API was reached; the named resource genuinely does not exist


class AwsCollectionResult(BaseModel):
    """Wraps EVERY AWS collection call -- callers must always check
    `outcome` before trusting `items`; `items` is only ever meaningful
    when `outcome` is SUCCESS (non-empty), EMPTY, or PARTIAL (meaningful
    but KNOWN INCOMPLETE -- see `detail`)."""

    model_config = ConfigDict(extra="forbid")

    outcome: AwsCollectionOutcome
    resource_kind: str  # "CloudWatchAlarm" | "Ec2Instance" | "EcsService" | "CloudTrailEvent"
    account_id: str
    region: str
    detail: str
    items_count: int = 0


class CloudWatchAlarmObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alarm_name: str
    alarm_arn: str | None = None
    state_value: str | None = None  # "ALARM" | "OK" | "INSUFFICIENT_DATA"
    state_reason: str | None = None
    state_updated_timestamp: str | None = None
    namespace: str | None = None
    metric_name: str | None = None
    comparison_operator: str | None = None
    threshold: float | None = None
    evaluation_periods: int | None = None


class Ec2InstanceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str
    state_name: str | None = None  # "running" | "stopped" | "stopping" | "pending" | "shutting-down" | "terminated"
    state_transition_reason: str | None = None
    # DescribeInstanceStatus's own two independent checks -- "ok" |
    # "impaired" | "insufficient-data" | "not-applicable". None when
    # this process only had DescribeInstances evidence (status checks
    # were not collected or not yet available) -- never defaulted to
    # "ok".
    instance_status: str | None = None
    system_status: str | None = None
    launch_time: str | None = None


class EcsServiceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_arn: str
    service_name: str
    status: str | None = None  # "ACTIVE" | "DRAINING" | "INACTIVE"
    desired_count: int | None = None
    running_count: int | None = None
    pending_count: int | None = None
    deployment_rollout_state: str | None = None
    # Bounded, short "message @ timestamp" strings from the service's
    # own recent Events list -- never the full ECS event object, never
    # unbounded.
    recent_events: list[str] = []


class CloudTrailEventObservation(BaseModel):
    """Deliberately narrow -- CloudTrail's own `CloudTrailEvent` JSON
    blob can carry `requestParameters`/`responseElements`/session
    context that may include sensitive values; this process never even
    reads those fields out of the raw event at all (redaction by
    omission, never a regex that could miss something). Only the
    bounded, structurally safe management-event identity fields are
    kept."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_name: str
    event_time: str | None = None
    event_source: str | None = None
    username: str | None = None
    aws_region: str | None = None
    error_code: str | None = None
    # CloudTrail's own `Resources[].ResourceName` list -- bounded,
    # resource-identity-only (never a full ARN with embedded account
    # detail beyond what the caller already configured, never request
    # parameters).
    resource_names: list[str] = []


class AwsDetectionResult(str, Enum):
    CONFIRMED = "confirmed"  # real, direct evidence establishes this specific failure pattern
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # a suspicious signal exists, but not enough to confirm
    SOURCE_UNAVAILABLE = "source_unavailable"  # collection itself failed -- classification was never attempted


class AwsDetectionFinding(BaseModel):
    """One classifier's output for one specific AWS resource -- never
    emitted for a genuinely healthy resource (a detector returns an
    empty list for those). `result` is always CONFIRMED or
    INSUFFICIENT_EVIDENCE here; SOURCE_UNAVAILABLE is reserved for the
    collection layer itself (an `AwsCollectionResult`), not this model.

    `supporting_change_events` carries bounded, redacted CloudTrail
    management-event summaries (e.g. "RunInstances by alice@example.com
    at 2026-04-01T09:00:00Z") that occurred near this resource/window --
    Gate 2: "never automatically assumed to be the root cause". Temporal
    proximity alone is surfaced as a fact for a human/AI investigator to
    weigh, never as an established cause."""

    model_config = ConfigDict(extra="forbid")

    detector_id: str
    resource_kind: str  # "CloudWatchAlarm" | "Ec2Instance" | "EcsService"
    account_id: str
    region: str
    resource_id: str
    resource_arn: str | None = None
    result: AwsDetectionResult
    evidence: dict[str, str] = {}
    supporting_change_events: list[str] = []
    decision_rationale: str
    uncertainty_notes: str | None = None
