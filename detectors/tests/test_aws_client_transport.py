"""Correction round, Issues 1 and 6: transport-level negative controls
that inspect the EXACT boto3 operation arguments `Boto3AwsClient` sends
-- using `botocore.stub.Stubber`, the officially supported way to
validate request parameters without ever making a real network call
or needing real credentials. Dummy, obviously-fake credentials
("testing") are set via environment variables purely so boto3's own
request-signing step has something to sign with; `Stubber` intercepts
every call BEFORE it would ever reach a real AWS endpoint, so no live
AWS call is made anywhere in this file, confirmed by
`stubber.assert_no_pending_responses()`/exact `expected_params`
assertions below (a call with unexpected parameters raises
`StubAssertionError` rather than ever being sent).

This is the one test module in this package that DOES construct
`Boto3AwsClient` -- deliberately, since Issues 1/6 are specifically
about the exact arguments it builds, which a plain `AwsClientProtocol`
fake (used everywhere else in this suite) cannot observe at all.
"""

from datetime import UTC, datetime, timedelta

import pytest
from botocore.stub import Stubber

from detectors.clients.aws_client import (
    MAX_INSTANCE_IDS_PER_CALL,
    MAX_METRIC_DATAPOINTS_PER_QUERY,
    MAX_METRIC_LOOKBACK_MINUTES,
    MAX_METRIC_QUERIES,
    AwsConfigError,
    AwsObserverScope,
    Boto3AwsClient,
    CLOUDTRAIL_MAX_RESULTS,
)


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch):
    # Obviously-fake placeholder values -- never real credentials.
    # Stubber never lets a signed request actually reach the network.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def _client(**scope_overrides) -> Boto3AwsClient:
    fields = {"account_id": "123456789012", "region": "us-east-1"}
    fields.update(scope_overrides)
    scope = AwsObserverScope(**fields)
    return Boto3AwsClient(scope)


# ---------------------------------------------------------------------
# Issue 1: EC2 DescribeInstances/DescribeInstanceStatus must NEVER
# combine InstanceIds with MaxResults.
# ---------------------------------------------------------------------


async def test_describe_instances_never_sends_maxresults_alongside_instance_ids():
    client = _client(enrolled_instance_ids=("i-0123456789abcdef0", "i-0123456789abcdef1"))
    stubber = Stubber(client._ec2)
    stubber.add_response(
        "describe_instances",
        {"Reservations": []},
        expected_params={"InstanceIds": ["i-0123456789abcdef0", "i-0123456789abcdef1"]},
    )
    stubber.activate()
    try:
        await client.describe_instances()
        stubber.assert_no_pending_responses()
    finally:
        stubber.deactivate()


async def test_describe_instance_status_never_sends_maxresults_alongside_instance_ids():
    client = _client(enrolled_instance_ids=("i-0123456789abcdef0",))
    stubber = Stubber(client._ec2)
    stubber.add_response(
        "describe_instance_status",
        {"InstanceStatuses": []},
        expected_params={"InstanceIds": ["i-0123456789abcdef0"], "IncludeAllInstances": True},
    )
    stubber.activate()
    try:
        await client.describe_instance_status()
        stubber.assert_no_pending_responses()
    finally:
        stubber.deactivate()


async def test_describe_instances_batches_enrolled_ids_without_dropping_any():
    """Reproduces the exact independent-review finding's own
    constraint: removing MaxResults must never silently drop
    enrollment -- more ids than MAX_INSTANCE_IDS_PER_CALL are split
    into bounded batches, and the client's own synthetic NextToken
    drives the SECOND batch through unmodified."""
    many_ids = tuple(f"i-{i:017x}" for i in range(MAX_INSTANCE_IDS_PER_CALL + 3))
    client = _client(enrolled_instance_ids=many_ids)
    stubber = Stubber(client._ec2)
    first_batch = list(many_ids[:MAX_INSTANCE_IDS_PER_CALL])
    second_batch = list(many_ids[MAX_INSTANCE_IDS_PER_CALL:])
    stubber.add_response("describe_instances", {"Reservations": []}, expected_params={"InstanceIds": first_batch})
    stubber.add_response("describe_instances", {"Reservations": []}, expected_params={"InstanceIds": second_batch})
    stubber.activate()
    try:
        first_response = await client.describe_instances()
        assert first_response["NextToken"] == str(MAX_INSTANCE_IDS_PER_CALL)
        second_response = await client.describe_instances(next_token=first_response["NextToken"])
        assert "NextToken" not in second_response
        stubber.assert_no_pending_responses()
    finally:
        stubber.deactivate()


# ---------------------------------------------------------------------
# Issue 1: CloudTrail LookupEvents MaxResults must be <= 50, never 100.
# ---------------------------------------------------------------------


async def test_lookup_events_sends_a_valid_max_results_value():
    client = _client()
    stubber = Stubber(client._cloudtrail)
    start, end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, 1, tzinfo=UTC)
    stubber.add_response(
        "lookup_events", {"Events": []},
        expected_params={"StartTime": start, "EndTime": end, "MaxResults": CLOUDTRAIL_MAX_RESULTS},
    )
    stubber.activate()
    try:
        assert CLOUDTRAIL_MAX_RESULTS <= 50  # the real, hard AWS-enforced ceiling for this parameter
        await client.lookup_events(start_time=start, end_time=end)
        stubber.assert_no_pending_responses()
    finally:
        stubber.deactivate()


# ---------------------------------------------------------------------
# Issue 6: GetMetricData's complete, bounded API contract.
# ---------------------------------------------------------------------


def _valid_query(period: int = 60) -> dict:
    return {
        "Id": "q1",
        "MetricStat": {
            "Metric": {"Namespace": "AWS/EC2", "MetricName": "CPUUtilization", "Dimensions": []},
            "Period": period,
            "Stat": "Average",
        },
        "ReturnData": True,
    }


async def test_get_metric_data_sends_required_start_and_end_time():
    client = _client()
    client._enable_get_metric_data = True
    start, end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, 0, 30, tzinfo=UTC)
    stubber = Stubber(client._cloudwatch)
    stubber.add_response(
        "get_metric_data", {"MetricDataResults": []},
        expected_params={"MetricDataQueries": [_valid_query()], "StartTime": start, "EndTime": end},
    )
    stubber.activate()
    try:
        await client.get_metric_data([_valid_query()], start_time=start, end_time=end)
        stubber.assert_no_pending_responses()
    finally:
        stubber.deactivate()


async def test_get_metric_data_disabled_by_default_never_reaches_the_transport():
    client = _client()  # enable_get_metric_data defaults False
    start, end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, 0, 30, tzinfo=UTC)
    with pytest.raises(AwsConfigError):
        await client.get_metric_data([_valid_query()], start_time=start, end_time=end)


async def test_get_metric_data_rejects_end_before_start():
    client = _client()
    client._enable_get_metric_data = True
    start, end = datetime(2026, 4, 1, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC)
    with pytest.raises(AwsConfigError):
        await client.get_metric_data([_valid_query()], start_time=start, end_time=end)


async def test_get_metric_data_rejects_a_window_longer_than_the_lookback_bound():
    client = _client()
    client._enable_get_metric_data = True
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = start + timedelta(minutes=MAX_METRIC_LOOKBACK_MINUTES + 1)
    with pytest.raises(AwsConfigError):
        await client.get_metric_data([_valid_query()], start_time=start, end_time=end)


async def test_get_metric_data_rejects_too_many_queries():
    client = _client()
    client._enable_get_metric_data = True
    start, end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, 0, 30, tzinfo=UTC)
    queries = [_valid_query()] * (MAX_METRIC_QUERIES + 1)
    for i, q in enumerate(queries):
        q["Id"] = f"q{i}"
    with pytest.raises(AwsConfigError):
        await client.get_metric_data(queries, start_time=start, end_time=end)


async def test_get_metric_data_rejects_cross_account_queries():
    client = _client()
    client._enable_get_metric_data = True
    start, end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, 0, 30, tzinfo=UTC)
    query = _valid_query()
    query["AccountId"] = "999999999999"
    with pytest.raises(AwsConfigError):
        await client.get_metric_data([query], start_time=start, end_time=end)


async def test_get_metric_data_rejects_a_sub_minimum_period():
    client = _client()
    client._enable_get_metric_data = True
    start, end = datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 1, 0, 30, tzinfo=UTC)
    with pytest.raises(AwsConfigError):
        await client.get_metric_data([_valid_query(period=1)], start_time=start, end_time=end)


async def test_get_metric_data_datapoint_bound_is_never_reachable_within_the_other_two_bounds():
    """Documents the actual relationship between the three bounds: with
    MIN_METRIC_PERIOD_SECONDS and MAX_METRIC_LOOKBACK_MINUTES both
    enforced, the worst case is `(MAX_METRIC_LOOKBACK_MINUTES * 60) /
    MIN_METRIC_PERIOD_SECONDS` datapoints -- this must stay comfortably
    under MAX_METRIC_DATAPOINTS_PER_QUERY, confirming the datapoint
    ceiling is a genuine defense-in-depth bound and not silently
    inconsistent with the other two."""
    worst_case_datapoints = (MAX_METRIC_LOOKBACK_MINUTES * 60) / 60  # 60 == MIN_METRIC_PERIOD_SECONDS
    assert worst_case_datapoints <= MAX_METRIC_DATAPOINTS_PER_QUERY


async def test_get_metric_data_accepts_the_maximum_valid_window_and_minimum_period():
    """Positive control: the largest allowed window combined with the
    smallest allowed period must still succeed -- the bounds must not
    be so strict they reject legitimate, fully-compliant requests."""
    client = _client()
    client._enable_get_metric_data = True
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = start + timedelta(minutes=MAX_METRIC_LOOKBACK_MINUTES)
    query = _valid_query(period=60)
    stubber = Stubber(client._cloudwatch)
    stubber.add_response(
        "get_metric_data", {"MetricDataResults": []},
        expected_params={"MetricDataQueries": [query], "StartTime": start, "EndTime": end},
    )
    stubber.activate()
    try:
        await client.get_metric_data([query], start_time=start, end_time=end)
        stubber.assert_no_pending_responses()
    finally:
        stubber.deactivate()
