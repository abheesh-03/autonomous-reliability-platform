"""Phase 13, Gate 1/2: pagination boundaries, malformed responses, and
partial-result handling for `detectors.aws.collector` -- mirrors
`test_kubernetes_pagination_and_partial_collection.py`'s own intent for
the AWS observer. A plain in-test fake implements `AwsClientProtocol`;
never boto3, never a network call."""

from detectors.aws.collector import collect_cloudwatch_alarms, collect_ec2_instances
from detectors.clients.aws_client import AwsForbiddenError, AwsObserverScope
from detectors.schemas.aws import AwsCollectionOutcome

ACCOUNT_ID = "123456789012"
REGION = "us-east-1"


class _PagedAlarmsClient:
    """Returns `pages` (a list of (items, next_token) tuples) in
    sequence, one per call to describe_alarms -- models real
    continuation-token pagination deterministically."""

    def __init__(self, scope: AwsObserverScope, pages: list[tuple[list[dict], str | None]]) -> None:
        self._scope = scope
        self._pages = list(pages)
        self._calls = 0

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def describe_alarms(self, *, next_token=None) -> dict:
        items, token = self._pages[self._calls]
        self._calls += 1
        return {"MetricAlarms": items, "NextToken": token}


class _AlwaysForbiddenAfterFirstPage:
    def __init__(self, scope: AwsObserverScope, first_page_items: list[dict]) -> None:
        self._scope = scope
        self._first_page_items = first_page_items
        self._calls = 0

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def describe_alarms(self, *, next_token=None) -> dict:
        self._calls += 1
        if self._calls == 1:
            return {"MetricAlarms": self._first_page_items, "NextToken": "next-page-token"}
        raise AwsForbiddenError("AWS API returned AccessDenied")


def _scope(**overrides) -> AwsObserverScope:
    fields = {"account_id": ACCOUNT_ID, "region": REGION, "enrolled_alarm_names": ("alarm-a", "alarm-b")}
    fields.update(overrides)
    return AwsObserverScope(**fields)


def _alarm(name: str) -> dict:
    return {"AlarmName": name, "StateValue": "OK"}


async def test_follows_continuation_token_across_pages():
    scope = _scope()
    client = _PagedAlarmsClient(scope, pages=[([_alarm("alarm-a")], "tok-1"), ([_alarm("alarm-b")], None)])
    result, items = await collect_cloudwatch_alarms(client)
    assert result.outcome == AwsCollectionOutcome.SUCCESS
    assert len(items) == 2


async def test_empty_first_page_with_continuation_is_never_reported_complete():
    """Reproduces the exact class of finding Phase 12A's own correction
    round caught for Kubernetes: a page with zero items but a real
    continuation token must never be silently treated as a complete,
    empty result."""
    scope = _scope()
    client = _AlwaysForbiddenAfterFirstPage(scope, first_page_items=[])
    result, items = await collect_cloudwatch_alarms(client)
    assert result.outcome == AwsCollectionOutcome.FORBIDDEN  # a later page failed -- never EMPTY
    assert items == []


async def test_a_later_page_failing_preserves_earlier_real_evidence_as_partial():
    scope = _scope()
    client = _AlwaysForbiddenAfterFirstPage(scope, first_page_items=[_alarm("alarm-a")])
    result, items = await collect_cloudwatch_alarms(client)
    assert result.outcome == AwsCollectionOutcome.FORBIDDEN
    assert len(items) == 1  # the first page's real evidence is preserved, never discarded


async def test_malformed_item_is_skipped_but_forces_incomplete():
    scope = _scope()
    client = _PagedAlarmsClient(scope, pages=[([{"NoAlarmNameField": True}, _alarm("alarm-a")], None)])
    result, items = await collect_cloudwatch_alarms(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert len(items) == 1
    assert items[0].alarm_name == "alarm-a"


async def test_malformed_response_shape_on_first_page_is_malformed_outcome():
    scope = _scope()

    class _ShapelessClient:
        def __init__(self, scope):
            self._scope = scope

        @property
        def scope(self):
            return self._scope

        async def describe_alarms(self, *, next_token=None):
            return {"NotTheRightKey": []}

    client = _ShapelessClient(scope)
    result, items = await collect_cloudwatch_alarms(client)
    assert result.outcome == AwsCollectionOutcome.MALFORMED
    assert items == []


async def test_no_enrolled_alarms_is_empty_never_a_live_call():
    scope = _scope(enrolled_alarm_names=())

    class _NeverCalledClient:
        def __init__(self, scope):
            self._scope = scope

        @property
        def scope(self):
            return self._scope

        async def describe_alarms(self, *, next_token=None):
            raise AssertionError("describe_alarms must never be called with no enrolled alarms")

    client = _NeverCalledClient(scope)
    result, items = await collect_cloudwatch_alarms(client)
    assert result.outcome == AwsCollectionOutcome.EMPTY
    assert items == []


# ---------------------------------------------------------------------
# EC2: merged DescribeInstances + DescribeInstanceStatus completeness
# ---------------------------------------------------------------------


class _Ec2Client:
    def __init__(self, scope, instances, statuses, *, status_error=None):
        self._scope = scope
        self._instances = instances
        self._statuses = statuses
        self._status_error = status_error

    @property
    def scope(self):
        return self._scope

    async def describe_instances(self, *, next_token=None):
        return {"Reservations": [{"Instances": self._instances}], "NextToken": None}

    async def describe_instance_status(self, *, next_token=None):
        if self._status_error:
            raise self._status_error
        return {"InstanceStatuses": self._statuses, "NextToken": None}


async def test_ec2_status_check_collection_failure_is_never_treated_as_healthy():
    scope = _scope(enrolled_alarm_names=(), enrolled_instance_ids=("i-0123456789abcdef0",))
    instances = [{"InstanceId": "i-0123456789abcdef0", "State": {"Name": "running"}}]
    client = _Ec2Client(scope, instances, [], status_error=AwsForbiddenError("AccessDenied"))
    result, items = await collect_ec2_instances(client)
    assert result.outcome == AwsCollectionOutcome.FORBIDDEN
    # The identity/state evidence that WAS collected is preserved, with instance_status/system_status left None.
    assert len(items) == 1
    assert items[0].instance_status is None
