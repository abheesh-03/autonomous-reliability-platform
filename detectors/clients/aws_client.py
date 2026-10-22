"""Phase 13, Gate 1: a bounded, READ-ONLY AWS observer client -- same
discipline as `kubernetes_client.py`: a FIXED, small set of read-only
calls, explicit enrollment/scope (never "scan the whole account"),
bounded timeouts/pagination/item counts, and an explicit, typed outcome
for every call (never a bare exception the caller must guess the
meaning of).

Security, enforced structurally (not just by convention):
  - `AwsClientProtocol` lists exactly 8 methods, every one of them a
    read-only AWS API call (STS GetCallerIdentity; CloudWatch
    DescribeAlarms/GetMetricData; CloudTrail LookupEvents; EC2
    DescribeInstances/DescribeInstanceStatus; ECS
    ListServices/DescribeServices). There is no method anywhere in
    this module that can call StartInstances, StopInstances,
    RebootInstances, UpdateService, RunTask, PutMetricAlarm,
    CreateTrail, PutLogEvents, or any other mutating AWS API --
    `Boto3AwsClient` never constructs a boto3 client for any service
    beyond the four named above, and it never calls boto3's own
    generic/dynamic `client.meta.service_model` write operations.
  - Account/Region are explicit, validated, REQUIRED construction
    parameters -- there is no "ambient default account" fallback.
    `verify_identity()` calls STS GetCallerIdentity and fails closed
    (`AwsIdentityMismatchError`) if the live account does not match
    the configured one, exactly mirroring Gate 1's "fail closed on
    account/Region mismatch" requirement; callers (the collector) MUST
    call this before any other collection call in a live run.
  - every resource identifier a caller passes in (instance ids, ECS
    cluster/service identifiers, CloudWatch alarm names) is validated
    against a real AWS identifier shape before it is ever placed into
    a boto3 call parameter -- malformed/ambiguous input is rejected
    with `AwsConfigError`, never silently coerced or passed through.
  - this module never logs, prints, or includes in any exception
    message a credential value, access key, or session token -- every
    error message is built ONLY from the exception's own TYPE NAME or
    AWS-reported error CODE, never its full textual payload (which can
    occasionally echo back request parameters).
  - `GetMetricData` is the one call with a genuine per-request AWS
    cost; `Boto3AwsClient.get_metric_data` is reachable ONLY if the
    caller explicitly constructed it with `enable_get_metric_data=True`
    (Gate 7: "GetMetricData must be disabled by default") and always
    enforces `MAX_METRIC_QUERIES`/`MAX_METRIC_LOOKBACK_MINUTES`.
"""

import re
from dataclasses import dataclass
from typing import Protocol

DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_READ_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRY_ATTEMPTS = 2

# Defensive cardinality/page caps -- mirrors kubernetes_client.py's own
# MAX_ITEMS discipline. Applied as the boto3 `MaxResults`/page-size
# parameter on every paginated call, AND as the collector's own
# bounded-pages ceiling (detectors/aws/collector.py).
MAX_ITEMS = 100
MAX_PAGES = 5

# Correction round, Issue 1: CloudTrail's own LookupEvents `MaxResults`
# parameter only accepts 1-50 -- NOT the generic MAX_ITEMS=100 bound
# every other paginated call here uses. Using a value AWS itself
# rejects would never surface as a logic bug against a fake client,
# only against the real API -- kept as its own named constant so it
# can never silently drift back to MAX_ITEMS.
CLOUDTRAIL_MAX_RESULTS = 50

# Correction round, Issue 1: AWS explicitly prohibits combining EC2's
# `InstanceIds` parameter with `MaxResults` on BOTH DescribeInstances
# and DescribeInstanceStatus -- this client therefore never sends
# MaxResults on either call (see describe_instances/
# describe_instance_status below); the enrolled instance id list is
# instead split into bounded batches of at most this many ids per
# physical call, with the collector's own existing bounded-pagination
# loop (detectors/aws/collector.py, MAX_PAGES) driving through the
# batches via a synthetic, self-issued continuation token -- never an
# unbounded single request, and never a silently dropped enrollment.
MAX_INSTANCE_IDS_PER_CALL = 50

# Gate 7: "GetMetricData must be disabled by default with explicit
# per-run cost-oriented limits." Even when a caller explicitly opts in,
# these bounds are never exceeded by this client.
MAX_METRIC_QUERIES = 5
MAX_METRIC_LOOKBACK_MINUTES = 60
# Correction round, Issue 6: a defensive per-query datapoint ceiling --
# computed from the caller's own (StartTime, EndTime) window and each
# query's own MetricStat.Period -- so a caller cannot request a huge
# number of datapoints merely by specifying a very fine-grained period
# within an otherwise-bounded time window.
MAX_METRIC_DATAPOINTS_PER_QUERY = 1440
# CloudWatch's own minimum standard-resolution granularity; a smaller
# Period is high-resolution (sub-minute) and only valid for a narrow
# set of recently-published custom metrics -- never required by
# anything this client does, and rejected outright here so a caller
# cannot (accidentally or otherwise) request an unbounded-looking
# datapoint count via a tiny Period.
MIN_METRIC_PERIOD_SECONDS = 60

_ACCOUNT_ID_RE = re.compile(r"^\d{12}$")
_REGION_RE = re.compile(r"^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-\d$")
_INSTANCE_ID_RE = re.compile(r"^i-[0-9a-f]{8,17}$")
# ECS accepts either a bare cluster/service name or a full ARN for
# either parameter -- both are allowed here, nothing else.
_ECS_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
_ECS_ARN_RE = re.compile(r"^arn:aws[a-zA-Z-]*:ecs:(?P<region>[a-z0-9-]+):(?P<account_id>\d{12}):(cluster|service)/.+$")
_ALARM_NAME_MAX_CHARS = 255


class AwsConfigError(Exception):
    """A caller/configuration error (malformed account id/region/
    resource identifier, ambiguous enrollment, GetMetricData requested
    without opting in) -- never raised for a live API call failure."""


class AwsIdentityMismatchError(Exception):
    """STS GetCallerIdentity reported an account id different from the
    one this client was explicitly configured for -- Gate 1: "fail
    closed on account/Region mismatch". Never silently proceeds with
    collection against an unexpected account."""


class AwsUnavailableError(Exception):
    """The AWS API could not be reached at all (network/connection/
    credential failure), or returned a response this client cannot
    interpret -- never includes credential material."""


class AwsForbiddenError(Exception):
    """The AWS API was reached and responded with AccessDenied/
    UnauthorizedOperation -- distinct from AwsUnavailableError so a
    caller can tell "nothing answered" apart from "something answered
    and refused this request" (IAM)."""


class AwsThrottledError(Exception):
    """The AWS API was reached and responded with a throttling/rate-
    limit error -- distinct from both Forbidden and Unavailable; the
    correct caller response is to back off, never to guess a result."""


class AwsNotFoundError(Exception):
    """The AWS API was reached; the specific named resource genuinely
    does not exist."""


def validate_account_id(account_id: str) -> str:
    if not _ACCOUNT_ID_RE.match(account_id):
        raise AwsConfigError(f"account_id {account_id!r} is not a valid 12-digit AWS account id")
    return account_id


def validate_region(region: str) -> str:
    if not _REGION_RE.match(region):
        raise AwsConfigError(f"region {region!r} is not a valid AWS region identifier")
    return region


def validate_instance_id(instance_id: str) -> str:
    if not _INSTANCE_ID_RE.match(instance_id):
        raise AwsConfigError(f"instance id {instance_id!r} is not a valid EC2 instance id")
    return instance_id


def validate_ecs_identifier(value: str, *, kind: str, account_id: str, region: str) -> str:
    """Correction round (final), Issue 3: a bare name has no embedded
    account/region to check at all (it is always implicitly scoped to
    whichever account/region the client itself is configured for) --
    accepted as-is. An ARN form, however, carries its OWN account/
    region, and that embedded identity is validated against the
    caller's explicitly configured `account_id`/`region` BEFORE this
    ever returns successfully -- an ARN naming a different account or
    region is rejected outright, at scope-construction time, before
    any SDK call is ever made (never discovered later as a live
    AccessDenied/mismatch from AWS itself)."""
    if _ECS_NAME_RE.match(value):
        return value
    match = _ECS_ARN_RE.match(value)
    if not match:
        raise AwsConfigError(f"ECS {kind} {value!r} is not a valid ECS name or ARN")
    if match.group("region") != region or match.group("account_id") != account_id:
        raise AwsConfigError(
            f"ECS {kind} ARN {value!r} belongs to account {match.group('account_id')!r}/region "
            f"{match.group('region')!r}, not the configured account {account_id!r}/region {region!r}"
        )
    return value


def validate_alarm_name(name: str) -> str:
    if not name or not name.strip() or len(name) > _ALARM_NAME_MAX_CHARS:
        raise AwsConfigError(f"CloudWatch alarm name {name!r} is blank or exceeds {_ALARM_NAME_MAX_CHARS} characters")
    return name


@dataclass(frozen=True)
class AwsObserverScope:
    """Explicit resource enrollment -- Gate 1: "Require explicit
    resource enrollment/scope" / "Do not automatically scan every
    resource in an AWS account." Every list here is validated at
    construction; an empty scope is valid (it simply means that
    resource kind is never collected), but a non-empty list must
    contain only well-formed identifiers."""

    account_id: str
    region: str
    enrolled_alarm_names: tuple[str, ...] = ()
    enrolled_instance_ids: tuple[str, ...] = ()
    enrolled_ecs_clusters: tuple[str, ...] = ()
    # (cluster, service) pairs -- a service identifier is only ever
    # meaningful paired with the cluster it belongs to.
    enrolled_ecs_services: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        validate_account_id(self.account_id)
        validate_region(self.region)
        for name in self.enrolled_alarm_names:
            validate_alarm_name(name)
        for instance_id in self.enrolled_instance_ids:
            validate_instance_id(instance_id)
        for cluster in self.enrolled_ecs_clusters:
            validate_ecs_identifier(cluster, kind="cluster", account_id=self.account_id, region=self.region)
        for cluster, service in self.enrolled_ecs_services:
            validate_ecs_identifier(cluster, kind="cluster", account_id=self.account_id, region=self.region)
            validate_ecs_identifier(service, kind="service", account_id=self.account_id, region=self.region)


class AwsClientProtocol(Protocol):
    """The ONE mockable seam the rest of this package depends on --
    `detectors/aws/collector.py` and the full pipeline only ever import
    this Protocol's shape, never `Boto3AwsClient` directly, so the
    entire detector suite (and `python -m detectors replay`) can run
    with a plain in-test fake and NEVER requires live AWS credentials
    or a network call."""

    @property
    def scope(self) -> AwsObserverScope: ...

    async def verify_identity(self) -> str:
        """STS GetCallerIdentity. Returns the live account id on
        success. Raises AwsIdentityMismatchError if it does not match
        `scope.account_id`."""
        ...

    async def describe_alarms(self, *, next_token: str | None = None) -> dict: ...

    async def get_metric_data(self, queries: list[dict], *, start_time, end_time) -> dict: ...

    async def lookup_events(self, *, start_time, end_time, next_token: str | None = None) -> dict: ...

    async def describe_instances(self, *, next_token: str | None = None) -> dict: ...

    async def describe_instance_status(self, *, next_token: str | None = None) -> dict: ...

    async def list_services(self, cluster: str, *, next_token: str | None = None) -> dict: ...

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict: ...


def _classify_client_error(exc: Exception) -> Exception:
    """Maps a real botocore ClientError's own reported error Code --
    NEVER its full message text, which can echo back request
    parameters -- onto this module's typed exception vocabulary. Any
    code this module does not specifically recognize is conservatively
    treated as AwsUnavailableError (never silently treated as a
    healthy/empty result)."""
    response = getattr(exc, "response", None) or {}
    code = response.get("Error", {}).get("Code", "")
    forbidden_codes = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "AuthFailure"}
    throttled_codes = {
        "Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException",
        "ProvisionedThroughputExceededException", "SlowDown",
    }
    not_found_codes = {
        "ResourceNotFoundException", "InvalidInstanceID.NotFound", "ClusterNotFoundException",
        "ServiceNotFoundException",
    }
    if code in forbidden_codes:
        return AwsForbiddenError(f"AWS API returned {code}")
    if code in throttled_codes:
        return AwsThrottledError(f"AWS API returned {code}")
    if code in not_found_codes:
        return AwsNotFoundError(f"AWS API returned {code}")
    return AwsUnavailableError(f"AWS API returned an unexpected error: {type(exc).__name__}")


class Boto3AwsClient:
    """The real, live implementation of `AwsClientProtocol`, backed by
    `boto3`/`botocore`. Constructing this class NEVER makes a network
    call by itself (boto3 sessions/clients are lazy) -- the only way
    this class ever reaches a real AWS endpoint is via one of its own
    8 read-only methods being awaited, each of which is a single,
    bounded, synchronous boto3 call executed off the event loop thread
    via `asyncio.to_thread` (boto3 itself has no native asyncio
    support).

    Never constructed anywhere in this package's own test suite -- see
    `AwsClientProtocol`'s own docstring; every test uses a plain fake.
    """

    def __init__(
        self,
        scope: AwsObserverScope,
        *,
        profile: str | None = None,
        enable_get_metric_data: bool = False,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_RETRY_ATTEMPTS,
    ) -> None:
        import boto3  # imported lazily: this module itself has zero import-time dependency on boto3,
        from botocore.config import Config  # so every other module in this package (and every test that

        # never touches Boto3AwsClient) never needs boto3/botocore installed at import time either --
        # only the one real, live code path does.

        self._scope = scope
        self._enable_get_metric_data = enable_get_metric_data
        boto_config = Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": max_attempts, "mode": "standard"},
            region_name=scope.region,
        )
        # The SDK credential provider chain, scoped to an explicit
        # profile if given -- Gate 1: "Use the SDK credential provider
        # chain with a selected profile or role." Never a hardcoded
        # access key anywhere in this module.
        session = boto3.Session(profile_name=profile, region_name=scope.region)
        if scope.region not in session.get_available_regions("ec2"):
            raise AwsConfigError(f"region {scope.region!r} is not a known AWS region for the EC2 service")
        self._sts = session.client("sts", config=boto_config)
        self._cloudwatch = session.client("cloudwatch", config=boto_config)
        self._cloudtrail = session.client("cloudtrail", config=boto_config)
        self._ec2 = session.client("ec2", config=boto_config)
        self._ecs = session.client("ecs", config=boto_config)

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def _call(self, fn, *args, **kwargs) -> dict:
        import asyncio
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except ClientError as exc:
            raise _classify_client_error(exc) from exc
        except BotoCoreError as exc:
            # Covers NoCredentialsError/EndpointConnectionError/
            # ConnectTimeoutError/ReadTimeoutError and every other
            # botocore-internal failure that never reached a real AWS
            # error-coded response at all.
            raise AwsUnavailableError(f"could not complete the AWS API call: {type(exc).__name__}") from exc

    async def verify_identity(self) -> str:
        body = await self._call(self._sts.get_caller_identity)
        live_account = str(body.get("Account", ""))
        if live_account != self._scope.account_id:
            raise AwsIdentityMismatchError(
                f"configured account_id {self._scope.account_id!r} does not match the live STS-reported "
                f"account {live_account!r} -- refusing to observe"
            )
        return live_account

    async def describe_alarms(self, *, next_token: str | None = None) -> dict:
        if not self._scope.enrolled_alarm_names:
            raise AwsConfigError("describe_alarms called with no enrolled_alarm_names configured")
        kwargs: dict = {"AlarmNames": list(self._scope.enrolled_alarm_names), "MaxRecords": MAX_ITEMS}
        if next_token:
            kwargs["NextToken"] = next_token
        return await self._call(self._cloudwatch.describe_alarms, **kwargs)

    async def get_metric_data(self, queries: list[dict], *, start_time, end_time) -> dict:
        """Correction round, Issue 6: AWS requires StartTime/EndTime on
        every GetMetricData call -- both are now REQUIRED keyword
        arguments, never silently omitted. The requested window is
        validated to be short and well-formed (never more than
        MAX_METRIC_LOOKBACK_MINUTES, never backwards/zero-length), the
        query count is bounded, every query's own implied datapoint
        count (window / Period) is bounded, and no query may request
        cross-account data (an 'AccountId' field) -- this client
        observes exactly one, explicitly configured account."""
        if not self._enable_get_metric_data:
            raise AwsConfigError("get_metric_data called without enable_get_metric_data=True -- disabled by default (cost)")
        if not queries or len(queries) > MAX_METRIC_QUERIES:
            raise AwsConfigError(f"get_metric_data requires 1-{MAX_METRIC_QUERIES} queries, got {len(queries)}")
        if end_time <= start_time:
            raise AwsConfigError("get_metric_data requires end_time to be strictly after start_time")
        window_seconds = (end_time - start_time).total_seconds()
        if window_seconds > MAX_METRIC_LOOKBACK_MINUTES * 60:
            raise AwsConfigError(
                f"get_metric_data window ({window_seconds:.0f}s) exceeds the bounded "
                f"{MAX_METRIC_LOOKBACK_MINUTES}-minute lookback limit"
            )
        for q in queries:
            if not isinstance(q, dict) or not q.get("Id"):
                raise AwsConfigError("each metric query must be a dict with a non-empty 'Id'")
            if "AccountId" in q:
                raise AwsConfigError(
                    f"query {q.get('Id')!r} requests cross-account data (an 'AccountId' field) -- "
                    "this client only ever observes its own explicitly configured account"
                )
            metric_stat = q.get("MetricStat")
            if isinstance(metric_stat, dict):
                period = metric_stat.get("Period")
                if not isinstance(period, int) or period < MIN_METRIC_PERIOD_SECONDS:
                    raise AwsConfigError(
                        f"query {q['Id']!r}: MetricStat.Period must be an integer >= "
                        f"{MIN_METRIC_PERIOD_SECONDS} seconds"
                    )
                if window_seconds / period > MAX_METRIC_DATAPOINTS_PER_QUERY:
                    raise AwsConfigError(
                        f"query {q['Id']!r} would return more than {MAX_METRIC_DATAPOINTS_PER_QUERY} "
                        "datapoints for the requested window/period"
                    )
        return await self._call(
            self._cloudwatch.get_metric_data, MetricDataQueries=queries, StartTime=start_time, EndTime=end_time
        )

    async def lookup_events(self, *, start_time, end_time, next_token: str | None = None) -> dict:
        kwargs: dict = {"StartTime": start_time, "EndTime": end_time, "MaxResults": CLOUDTRAIL_MAX_RESULTS}
        if next_token:
            kwargs["NextToken"] = next_token
        return await self._call(self._cloudtrail.lookup_events, **kwargs)

    def _next_instance_id_batch(self, next_token: str | None) -> tuple[list[str], int, int]:
        """Correction round, Issue 1: `InstanceIds` and `MaxResults`
        are mutually exclusive on both DescribeInstances and
        DescribeInstanceStatus -- AWS rejects the combination outright.
        This client therefore paginates the ENROLLED id list itself,
        never AWS's own NextToken mechanism, for either call: `offset`
        is encoded as a plain string in the returned response's own
        "NextToken" field (see describe_instances/
        describe_instance_status below), so the collector's existing
        bounded-pagination loop drives through the enrolled ids in
        batches of at most MAX_INSTANCE_IDS_PER_CALL without ever
        dropping any of them."""
        ids = list(self._scope.enrolled_instance_ids)
        offset = int(next_token) if next_token else 0
        batch = ids[offset : offset + MAX_INSTANCE_IDS_PER_CALL]
        next_offset = offset + len(batch)
        return batch, next_offset, len(ids)

    async def describe_instances(self, *, next_token: str | None = None) -> dict:
        if not self._scope.enrolled_instance_ids:
            raise AwsConfigError("describe_instances called with no enrolled_instance_ids configured")
        batch, next_offset, total = self._next_instance_id_batch(next_token)
        # Never MaxResults alongside InstanceIds -- AWS rejects that
        # combination for this call.
        body = await self._call(self._ec2.describe_instances, InstanceIds=batch)
        body = dict(body)
        if next_offset < total:
            body["NextToken"] = str(next_offset)
        return body

    async def describe_instance_status(self, *, next_token: str | None = None) -> dict:
        if not self._scope.enrolled_instance_ids:
            raise AwsConfigError("describe_instance_status called with no enrolled_instance_ids configured")
        batch, next_offset, total = self._next_instance_id_batch(next_token)
        # Never MaxResults alongside InstanceIds -- AWS rejects that
        # combination for this call too. IncludeAllInstances remains
        # valid alongside InstanceIds (only MaxResults is the
        # prohibited combination) -- kept so this process can still
        # distinguish "intentionally stopped" from "impaired" rather
        # than AWS silently omitting non-running instances.
        body = await self._call(self._ec2.describe_instance_status, InstanceIds=batch, IncludeAllInstances=True)
        body = dict(body)
        if next_offset < total:
            body["NextToken"] = str(next_offset)
        return body

    async def list_services(self, cluster: str, *, next_token: str | None = None) -> dict:
        validate_ecs_identifier(cluster, kind="cluster", account_id=self._scope.account_id, region=self._scope.region)
        kwargs: dict = {"cluster": cluster, "maxResults": MAX_ITEMS}
        if next_token:
            kwargs["nextToken"] = next_token
        return await self._call(self._ecs.list_services, **kwargs)

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict:
        validate_ecs_identifier(cluster, kind="cluster", account_id=self._scope.account_id, region=self._scope.region)
        for name in service_names:
            validate_ecs_identifier(name, kind="service", account_id=self._scope.account_id, region=self._scope.region)
        if not service_names or len(service_names) > 10:
            # ECS's own real DescribeServices limit is 10 services per call.
            raise AwsConfigError("describe_services requires 1-10 service_names per call")
        return await self._call(self._ecs.describe_services, cluster=cluster, services=service_names)
