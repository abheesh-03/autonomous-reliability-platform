"""Correction round, Issue 2: ECS collection must never report SUCCESS
when any part of it (ListServices discovery, DescribeServices, ARN
parsing) was itself incomplete, and every bound must apply to the
WHOLE observation run, not merely to one cluster at a time. A plain
in-test fake implements `AwsClientProtocol`; never boto3, never a
network call."""

from detectors.aws.collector import (
    MAX_ECS_CLUSTERS_PER_RUN,
    MAX_ECS_DESCRIBE_BATCHES_PER_RUN,
    MAX_ECS_SERVICE_PAIRS_PER_RUN,
    collect_ecs_services,
)
from detectors.clients.aws_client import MAX_PAGES, AwsObserverScope
from detectors.schemas.aws import AwsCollectionOutcome

ACCOUNT_ID = "123456789012"
REGION = "us-east-1"


def _scope(**overrides) -> AwsObserverScope:
    fields = {"account_id": ACCOUNT_ID, "region": REGION}
    fields.update(overrides)
    return AwsObserverScope(**fields)


def _service(name: str, cluster_arn: str, *, desired=1, running=1) -> dict:
    return {
        "serviceName": name, "clusterArn": cluster_arn, "status": "ACTIVE",
        "desiredCount": desired, "runningCount": running,
        "deployments": [{"status": "PRIMARY", "rolloutState": "COMPLETED"}], "events": [],
    }


# ---------------------------------------------------------------------
# THE Issue 2 reproduction: ListServices reaches MAX_PAGES with a
# continuation token still present -- must be PARTIAL, never SUCCESS.
# ---------------------------------------------------------------------


class _EcsAlwaysMorePagesClient:
    """ListServices NEVER terminates on its own (always returns a
    continuation token) -- models the exact independently-reproduced
    case: the bounded MAX_PAGES ceiling is reached while real evidence
    (service ARNs) was still being discovered."""

    def __init__(self, scope: AwsObserverScope) -> None:
        self._scope = scope
        self.list_calls = 0

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def list_services(self, cluster: str, *, next_token=None) -> dict:
        self.list_calls += 1
        return {"serviceArns": [f"svc-{self.list_calls}"], "nextToken": f"tok-{self.list_calls}"}

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict:
        services = [_service(n, f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod") for n in service_names]
        return {"services": services, "failures": []}


async def test_list_services_reaching_max_pages_with_continuation_is_never_reported_success():
    scope = _scope(enrolled_ecs_clusters=("prod",))
    client = _EcsAlwaysMorePagesClient(scope)
    result, items = await collect_ecs_services(client)

    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert client.list_calls == MAX_PAGES  # bounded, never an unbounded loop
    # Whatever real evidence WAS collected across the bounded pages is
    # preserved, never discarded, even though the collection as a
    # whole is honestly reported as incomplete.
    assert len(items) == MAX_PAGES


# ---------------------------------------------------------------------
# Malformed service ARNs in a ListServices page must force PARTIAL.
# ---------------------------------------------------------------------


class _EcsMalformedArnClient:
    def __init__(self, scope: AwsObserverScope) -> None:
        self._scope = scope

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def list_services(self, cluster: str, *, next_token=None) -> dict:
        return {"serviceArns": ["good-service", None, "", 42], "nextToken": None}

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict:
        services = [_service(n, f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod") for n in service_names]
        return {"services": services, "failures": []}


async def test_malformed_service_arns_force_partial_never_silently_dropped():
    scope = _scope(enrolled_ecs_clusters=("prod",))
    client = _EcsMalformedArnClient(scope)
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert len(items) == 1
    assert items[0].service_name == "good-service"


# ---------------------------------------------------------------------
# Incomplete/missing DescribeServices responses, and failures[], force
# PARTIAL.
# ---------------------------------------------------------------------


class _EcsDescribeServicesVariant:
    def __init__(self, scope: AwsObserverScope, describe_response) -> None:
        self._scope = scope
        self._describe_response = describe_response

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def list_services(self, cluster: str, *, next_token=None) -> dict:
        return {"serviceArns": ["svc-a", "svc-b"], "nextToken": None}

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict:
        return self._describe_response


async def test_missing_describe_services_response_shape_forces_partial():
    scope = _scope(enrolled_ecs_clusters=("prod",))
    client = _EcsDescribeServicesVariant(scope, {"NotTheRightKey": []})
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert items == []


async def test_describe_services_failures_list_forces_partial():
    scope = _scope(enrolled_ecs_clusters=("prod",))
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    client = _EcsDescribeServicesVariant(
        scope,
        {"services": [_service("svc-a", cluster_arn)], "failures": [{"arn": "svc-b", "reason": "MISSING"}]},
    )
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert len(items) == 1


# ---------------------------------------------------------------------
# Correction round (final), Issue 2: reconciling REQUESTED service
# identifiers against what DescribeServices actually returned --
# missing, unexpected, and duplicated service records.
# ---------------------------------------------------------------------


class _EcsDescribeServicesOnly:
    """No cluster-discovery at all -- every (cluster, service) pair is
    explicitly enrolled, so the batch sent to `describe_services` is
    deterministic and fully under the test's own control."""

    def __init__(self, scope: AwsObserverScope, describe_response: dict) -> None:
        self._scope = scope
        self._describe_response = describe_response
        self.describe_services_calls = []

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict:
        self.describe_services_calls.append((cluster, list(service_names)))
        return self._describe_response


async def test_requested_service_missing_from_both_services_and_failures_is_partial_never_empty():
    """THE exact independently-reproduced case: a requested service
    comes back in neither 'services' nor 'failures' at all --
    previously reported as EMPTY (a false healthy/empty result); must
    now be PARTIAL, because the requested service is unaccounted for."""
    scope = _scope(enrolled_ecs_services=(("prod", "checkout"),))
    client = _EcsDescribeServicesOnly(scope, {"services": [], "failures": []})
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert items == []
    assert "not accounted for" in result.detail


async def test_requested_service_fully_returned_is_success():
    """Positive control: a requested service that IS returned in
    'services' reconciles cleanly -- SUCCESS, never PARTIAL."""
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    scope = _scope(enrolled_ecs_services=(("prod", "checkout"),))
    client = _EcsDescribeServicesOnly(scope, {"services": [_service("checkout", cluster_arn)], "failures": []})
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.SUCCESS
    assert len(items) == 1
    assert items[0].service_name == "checkout"


async def test_requested_service_reported_as_a_failure_is_accounted_for_not_doubly_flagged_missing():
    """A requested service genuinely reported in 'failures' (e.g.
    MISSING) is accounted for by that -- it must NOT ALSO be reported
    as 'missing' (the existing failures-list check already forces
    PARTIAL for this; the new reconciliation must not duplicate or
    contradict that)."""
    scope = _scope(enrolled_ecs_services=(("prod", "checkout"),))
    client = _EcsDescribeServicesOnly(scope, {"services": [], "failures": [{"arn": "checkout", "reason": "MISSING"}]})
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert "not accounted for" not in result.detail  # accounted for via failures, not flagged as "missing"
    assert items == []


async def test_requested_service_via_arn_reconciles_against_a_bare_returned_name():
    """A requested service identifier given as a full ARN must
    reconcile correctly against DescribeServices' own bare
    `serviceName` in the response -- never falsely flagged as missing
    due to a name/ARN form mismatch."""
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    service_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:service/prod/checkout"
    scope = _scope(enrolled_ecs_services=(("prod", service_arn),))
    client = _EcsDescribeServicesOnly(scope, {"services": [_service("checkout", cluster_arn)], "failures": []})
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.SUCCESS
    assert len(items) == 1


async def test_unexpected_unrequested_service_in_response_forces_partial():
    """DescribeServices returning a service that was never requested
    at all is itself an anomaly -- the response cannot be trusted as a
    clean, complete answer to what was actually asked."""
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    scope = _scope(enrolled_ecs_services=(("prod", "checkout"),))
    client = _EcsDescribeServicesOnly(
        scope, {"services": [_service("checkout", cluster_arn), _service("never-requested", cluster_arn)], "failures": []}
    )
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert "never requested" in result.detail
    assert len(items) == 2  # real evidence still preserved, never discarded


async def test_duplicated_service_record_forces_partial():
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    scope = _scope(enrolled_ecs_services=(("prod", "checkout"),))
    client = _EcsDescribeServicesOnly(
        scope, {"services": [_service("checkout", cluster_arn), _service("checkout", cluster_arn)], "failures": []}
    )
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert "duplicate service record" in result.detail


async def test_genuinely_empty_result_with_nothing_requested_stays_empty():
    """Preserves the genuine EMPTY case -- no service was ever
    requested or discovered at all (never confused with 'something was
    requested but unaccounted for')."""
    scope = _scope(enrolled_ecs_clusters=("prod",))

    class _Client:
        def __init__(self, scope):
            self._scope = scope

        @property
        def scope(self):
            return self._scope

        async def list_services(self, cluster, *, next_token=None):
            return {"serviceArns": [], "nextToken": None}

    result, items = await collect_ecs_services(_Client(scope))
    assert result.outcome == AwsCollectionOutcome.EMPTY
    assert items == []


# ---------------------------------------------------------------------
# Total-per-run bounds: clusters, service pairs, DescribeServices
# batches -- never merely per individual cluster.
# ---------------------------------------------------------------------


class _EcsManyClustersClient:
    """Every enrolled cluster has exactly one healthy service -- used
    to prove the TOTAL cluster/pair/batch caps, not any per-cluster
    page limit, are what bound this run."""

    def __init__(self, scope: AwsObserverScope) -> None:
        self._scope = scope
        self.list_services_calls = 0
        self.describe_services_calls = 0

    @property
    def scope(self) -> AwsObserverScope:
        return self._scope

    async def list_services(self, cluster: str, *, next_token=None) -> dict:
        self.list_services_calls += 1
        return {"serviceArns": [f"{cluster}-svc"], "nextToken": None}

    async def describe_services(self, cluster: str, service_names: list[str]) -> dict:
        self.describe_services_calls += 1
        services = [_service(n, f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/{cluster}") for n in service_names]
        return {"services": services, "failures": []}


async def test_total_enrolled_clusters_are_capped_across_the_whole_run():
    many_clusters = tuple(f"cluster-{i}" for i in range(MAX_ECS_CLUSTERS_PER_RUN + 5))
    scope = _scope(enrolled_ecs_clusters=many_clusters)
    client = _EcsManyClustersClient(scope)
    result, items = await collect_ecs_services(client)

    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert client.list_services_calls == MAX_ECS_CLUSTERS_PER_RUN
    assert len(items) == MAX_ECS_CLUSTERS_PER_RUN  # never invented completeness beyond the cap


async def test_total_service_pairs_are_capped_across_the_whole_run():
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    many_pairs = tuple(("prod", f"svc-{i}") for i in range(MAX_ECS_SERVICE_PAIRS_PER_RUN + 10))
    scope = _scope(enrolled_ecs_services=many_pairs)

    class _Client:
        def __init__(self, scope):
            self._scope = scope

        @property
        def scope(self):
            return self._scope

        async def describe_services(self, cluster, service_names):
            return {"services": [_service(n, cluster_arn) for n in service_names], "failures": []}

    result, items = await collect_ecs_services(_Client(scope))
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert len(items) == MAX_ECS_SERVICE_PAIRS_PER_RUN


async def test_total_describe_services_batches_are_capped_across_the_whole_run():
    # Batches are formed PER CLUSTER -- scattering one service each
    # across many DISTINCT clusters (via explicit enrolled_ecs_services
    # pairs, which bypass the cluster-discovery cap entirely) produces
    # one small, unpacked batch per cluster. This keeps total pairs
    # (and total clusters) well under their own separate caps while
    # still forcing more batches than MAX_ECS_DESCRIBE_BATCHES_PER_RUN,
    # isolating the batch cap as the one actually-binding constraint.
    total_clusters = MAX_ECS_DESCRIBE_BATCHES_PER_RUN + 5
    assert total_clusters < MAX_ECS_SERVICE_PAIRS_PER_RUN
    many_pairs = tuple((f"cluster-{i}", "svc") for i in range(total_clusters))
    scope = _scope(enrolled_ecs_services=many_pairs)

    class _Client:
        def __init__(self, scope):
            self._scope = scope
            self.describe_services_calls = 0

        @property
        def scope(self):
            return self._scope

        async def describe_services(self, cluster, service_names):
            self.describe_services_calls += 1
            cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/{cluster}"
            return {"services": [_service(n, cluster_arn) for n in service_names], "failures": []}

    client = _Client(scope)
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.PARTIAL
    assert client.describe_services_calls == MAX_ECS_DESCRIBE_BATCHES_PER_RUN
    assert len(items) == MAX_ECS_DESCRIBE_BATCHES_PER_RUN


async def test_services_are_deduplicated_when_enrolled_both_explicitly_and_via_cluster_discovery():
    cluster_arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:cluster/prod"
    scope = _scope(enrolled_ecs_clusters=("prod",), enrolled_ecs_services=(("prod", "checkout"),))

    class _Client:
        def __init__(self, scope):
            self._scope = scope
            self.describe_services_calls = 0

        @property
        def scope(self):
            return self._scope

        async def list_services(self, cluster, *, next_token=None):
            return {"serviceArns": ["checkout"], "nextToken": None}  # the SAME service, discovered again

        async def describe_services(self, cluster, service_names):
            self.describe_services_calls += 1
            return {"services": [_service(n, cluster_arn) for n in service_names], "failures": []}

    client = _Client(scope)
    result, items = await collect_ecs_services(client)
    assert result.outcome == AwsCollectionOutcome.SUCCESS
    assert len(items) == 1  # never described/counted twice
    assert client.describe_services_calls == 1
