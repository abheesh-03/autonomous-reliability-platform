"""Phase 13, Gate 1: ties `AwsClientProtocol` (transport) and this
module's own per-call shape parsing together, producing one
`AwsCollectionResult` + a typed item list per resource kind -- mirrors
`detectors.kubernetes.collector`'s own separation between pagination/
outcome-classification and per-item parsing exactly.

Every collector function here is bounded: at most `MAX_PAGES`
continuation pages, at most `MAX_ITEMS` accumulated items. A failed,
forbidden, throttled, or malformed collection is NEVER silently
treated as "zero items exist" -- it is reported via the matching
`AwsCollectionOutcome`, and already-collected items from earlier pages
are always preserved, never discarded.
"""

from collections import Counter
from datetime import datetime

from detectors.clients.aws_client import (
    MAX_ITEMS,
    MAX_PAGES,
    AwsClientProtocol,
    AwsForbiddenError,
    AwsNotFoundError,
    AwsThrottledError,
    AwsUnavailableError,
)
from detectors.schemas.aws import (
    AwsCollectionOutcome,
    AwsCollectionResult,
    CloudTrailEventObservation,
    CloudWatchAlarmObservation,
    Ec2InstanceObservation,
    EcsServiceObservation,
)

# Correction round, Issue 2: TOTAL-per-run bounds for ECS collection --
# every one of these applies across ALL enrolled clusters/services
# combined, never merely to one cluster at a time (see
# collect_ecs_services's own docstring/comments below).
MAX_ECS_CLUSTERS_PER_RUN = 20
MAX_ECS_SERVICE_PAIRS_PER_RUN = MAX_ITEMS
# Batches are formed PER CLUSTER (at most 10 service identifiers per
# DescribeServices call, the real ECS API limit) -- a run with many
# small clusters (one service each) can need far more batches than
# `MAX_ECS_SERVICE_PAIRS_PER_RUN // 10` would suggest, so this is its
# own, independent bound rather than a value derived from the other
# two.
MAX_ECS_DESCRIBE_BATCHES_PER_RUN = 30

_FAILURE_OUTCOME_BY_EXCEPTION = {
    AwsForbiddenError: AwsCollectionOutcome.FORBIDDEN,
    AwsThrottledError: AwsCollectionOutcome.THROTTLED,
    AwsNotFoundError: AwsCollectionOutcome.NOT_FOUND,
    AwsUnavailableError: AwsCollectionOutcome.UNAVAILABLE,
}
_RECOGNIZED_FAILURES = tuple(_FAILURE_OUTCOME_BY_EXCEPTION)


def _iso(value: object) -> str | None:
    """boto3 parses AWS timestamps into real `datetime` objects --
    rendered here as ISO-8601 strings for this package's own bounded,
    JSON-serializable observation models. Never assumes a particular
    type; anything that is not a datetime/str is dropped (None), never
    fabricated."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _result(outcome: AwsCollectionOutcome, resource_kind: str, account_id: str, region: str, detail: str, items_count: int = 0) -> AwsCollectionResult:
    return AwsCollectionResult(
        outcome=outcome, resource_kind=resource_kind, account_id=account_id, region=region, detail=detail, items_count=items_count
    )


class _Malformed(Exception):
    """Internal-only: a page's own response body did not match the
    expected shape (never a real AWS-reported error) -- caught and
    turned into AwsCollectionOutcome.MALFORMED (first page) or a
    PARTIAL detail (a later page), exactly mirroring
    kubernetes/collector.py's own MALFORMED handling."""


async def _collect(
    resource_kind: str,
    account_id: str,
    region: str,
    fetch_page,  # async Callable[[str | None], tuple[list[dict], str | None]] -- raises on failure/malformed
    parse_items,  # Callable[[list[dict]], tuple[list, int]] -- (parsed, malformed_count)
) -> tuple[AwsCollectionResult, list]:
    accumulated: list = []
    malformed_total = 0
    next_token: str | None = None
    pages_fetched = 0

    while True:
        try:
            raw_items, next_token = await fetch_page(next_token)
        except _RECOGNIZED_FAILURES as exc:
            outcome = _FAILURE_OUTCOME_BY_EXCEPTION[type(exc)]
            if pages_fetched == 0:
                return _result(outcome, resource_kind, account_id, region, str(exc)), []
            return (
                _result(outcome, resource_kind, account_id, region, f"{len(accumulated)} item(s) preserved; a subsequent page failed: {exc}", len(accumulated)),
                accumulated,
            )
        except _Malformed as exc:
            if pages_fetched == 0:
                return _result(AwsCollectionOutcome.MALFORMED, resource_kind, account_id, region, str(exc)), []
            return (
                _result(AwsCollectionOutcome.PARTIAL, resource_kind, account_id, region, f"{len(accumulated)} item(s) preserved; a subsequent page was malformed: {exc}", len(accumulated)),
                accumulated,
            )

        pages_fetched += 1
        remaining_capacity = MAX_ITEMS - len(accumulated)
        page_items = raw_items[:remaining_capacity]
        page_was_truncated = len(raw_items) > len(page_items)

        parsed, malformed_count = parse_items(page_items)
        accumulated.extend(parsed)
        malformed_total += malformed_count

        if len(accumulated) >= MAX_ITEMS and (next_token or page_was_truncated):
            return (
                _result(
                    AwsCollectionOutcome.PARTIAL, resource_kind, account_id, region,
                    f"the bounded item cap ({MAX_ITEMS}) was reached while additional data remained uncollected",
                    len(accumulated),
                ),
                accumulated,
            )

        if not next_token:
            if malformed_total:
                return (
                    _result(
                        AwsCollectionOutcome.PARTIAL, resource_kind, account_id, region,
                        f"{len(accumulated)} item(s) parsed successfully; {malformed_total} item(s) could not be "
                        "parsed and were skipped -- never a clean healthy result",
                        len(accumulated),
                    ),
                    accumulated,
                )
            if accumulated:
                return (
                    _result(
                        AwsCollectionOutcome.SUCCESS, resource_kind, account_id, region,
                        f"{len(accumulated)} item(s) retrieved across {pages_fetched} page(s)", len(accumulated),
                    ),
                    accumulated,
                )
            return _result(AwsCollectionOutcome.EMPTY, resource_kind, account_id, region, "the API call succeeded; zero items were returned"), []

        if pages_fetched >= MAX_PAGES:
            return (
                _result(
                    AwsCollectionOutcome.PARTIAL, resource_kind, account_id, region,
                    f"the bounded page-fetch limit ({MAX_PAGES} pages) was reached while continuation pages remained",
                    len(accumulated),
                ),
                accumulated,
            )


# ---------------------------------------------------------------------
# A. CloudWatch alarms
# ---------------------------------------------------------------------


def _parse_alarms(raw_items: list[dict]) -> tuple[list[CloudWatchAlarmObservation], int]:
    parsed: list[CloudWatchAlarmObservation] = []
    malformed = 0
    for item in raw_items:
        name = item.get("AlarmName") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name:
            malformed += 1
            continue
        parsed.append(
            CloudWatchAlarmObservation(
                alarm_name=name,
                alarm_arn=item.get("AlarmArn"),
                state_value=item.get("StateValue"),
                state_reason=item.get("StateReason"),
                state_updated_timestamp=_iso(item.get("StateUpdatedTimestamp")),
                namespace=item.get("Namespace"),
                metric_name=item.get("MetricName"),
                comparison_operator=item.get("ComparisonOperator"),
                threshold=item.get("Threshold"),
                evaluation_periods=item.get("EvaluationPeriods"),
            )
        )
    return parsed, malformed


async def collect_cloudwatch_alarms(client: AwsClientProtocol) -> tuple[AwsCollectionResult, list[CloudWatchAlarmObservation]]:
    scope = client.scope
    if not scope.enrolled_alarm_names:
        return (
            _result(AwsCollectionOutcome.EMPTY, "CloudWatchAlarm", scope.account_id, scope.region, "no CloudWatch alarms are enrolled for observation"),
            [],
        )

    async def fetch_page(token: str | None) -> tuple[list[dict], str | None]:
        body = await client.describe_alarms(next_token=token)
        if not isinstance(body, dict) or not isinstance(body.get("MetricAlarms"), list):
            raise _Malformed("DescribeAlarms response had no 'MetricAlarms' list")
        return body["MetricAlarms"], body.get("NextToken")

    return await _collect("CloudWatchAlarm", scope.account_id, scope.region, fetch_page, _parse_alarms)


# ---------------------------------------------------------------------
# B. EC2 instances (DescribeInstances + DescribeInstanceStatus, merged)
# ---------------------------------------------------------------------


def _parse_instances(raw_items: list[dict]) -> tuple[list[Ec2InstanceObservation], int]:
    parsed: list[Ec2InstanceObservation] = []
    malformed = 0
    for item in raw_items:
        instance_id = item.get("InstanceId") if isinstance(item, dict) else None
        if not isinstance(instance_id, str) or not instance_id:
            malformed += 1
            continue
        state = item.get("State") or {}
        parsed.append(
            Ec2InstanceObservation(
                instance_id=instance_id,
                state_name=state.get("Name") if isinstance(state, dict) else None,
                state_transition_reason=item.get("StateTransitionReason"),
                launch_time=_iso(item.get("LaunchTime")),
            )
        )
    return parsed, malformed


async def collect_ec2_instances(client: AwsClientProtocol) -> tuple[AwsCollectionResult, list[Ec2InstanceObservation]]:
    """Merges DescribeInstances (authoritative state/launch evidence)
    with DescribeInstanceStatus (the two independent impaired/ok status
    checks) by instance_id into ONE observation per instance -- neither
    call alone carries both facets. If either collection is itself
    incomplete, the merged result is reported no better than the
    weaker of the two (never silently treated as fully reliable)."""
    scope = client.scope
    if not scope.enrolled_instance_ids:
        return (
            _result(AwsCollectionOutcome.EMPTY, "Ec2Instance", scope.account_id, scope.region, "no EC2 instances are enrolled for observation"),
            [],
        )

    async def fetch_instances_page(token: str | None) -> tuple[list[dict], str | None]:
        body = await client.describe_instances(next_token=token)
        if not isinstance(body, dict) or not isinstance(body.get("Reservations"), list):
            raise _Malformed("DescribeInstances response had no 'Reservations' list")
        instances: list[dict] = []
        for reservation in body["Reservations"]:
            if isinstance(reservation, dict) and isinstance(reservation.get("Instances"), list):
                instances.extend(reservation["Instances"])
        return instances, body.get("NextToken")

    instances_result, instances = await _collect("Ec2Instance", scope.account_id, scope.region, fetch_instances_page, _parse_instances)
    if instances_result.outcome not in (AwsCollectionOutcome.SUCCESS, AwsCollectionOutcome.EMPTY, AwsCollectionOutcome.PARTIAL):
        return instances_result, []

    def parse_statuses(raw_items: list[dict]) -> tuple[list[dict], int]:
        out = []
        malformed = 0
        for item in raw_items:
            instance_id = item.get("InstanceId") if isinstance(item, dict) else None
            if not isinstance(instance_id, str) or not instance_id:
                malformed += 1
                continue
            out.append(item)
        return out, malformed

    async def fetch_statuses_page(token: str | None) -> tuple[list[dict], str | None]:
        body = await client.describe_instance_status(next_token=token)
        if not isinstance(body, dict) or not isinstance(body.get("InstanceStatuses"), list):
            raise _Malformed("DescribeInstanceStatus response had no 'InstanceStatuses' list")
        return body["InstanceStatuses"], body.get("NextToken")

    statuses_result, statuses = await _collect("Ec2Instance", scope.account_id, scope.region, fetch_statuses_page, parse_statuses)

    status_by_instance = {}
    for s in statuses:
        instance_status = (s.get("InstanceStatus") or {}).get("Status")
        system_status = (s.get("SystemStatus") or {}).get("Status")
        status_by_instance[s["InstanceId"]] = (instance_status, system_status)

    merged = [
        obs.model_copy(update={"instance_status": status_by_instance.get(obs.instance_id, (None, None))[0],
                                "system_status": status_by_instance.get(obs.instance_id, (None, None))[1]})
        for obs in instances
    ]

    if statuses_result.outcome not in (AwsCollectionOutcome.SUCCESS, AwsCollectionOutcome.EMPTY, AwsCollectionOutcome.PARTIAL):
        return (
            _result(
                statuses_result.outcome, "Ec2Instance", scope.account_id, scope.region,
                f"instance identity/state evidence was collected, but status-check evidence was not: {statuses_result.detail}",
                len(merged),
            ),
            merged,
        )
    if instances_result.outcome == AwsCollectionOutcome.PARTIAL or statuses_result.outcome == AwsCollectionOutcome.PARTIAL:
        return (
            _result(AwsCollectionOutcome.PARTIAL, "Ec2Instance", scope.account_id, scope.region, "one of the two merged EC2 collections was itself incomplete", len(merged)),
            merged,
        )
    return instances_result.model_copy(update={"items_count": len(merged)}), merged


# ---------------------------------------------------------------------
# C. ECS services (ListServices + DescribeServices, batched)
# ---------------------------------------------------------------------


def _bare_service_name(identifier: str) -> str:
    """Correction round, Issue 2: a requested service identifier can
    legitimately be EITHER a bare name or a full ARN
    (arn:...:service/CLUSTER/SERVICE_NAME -- see
    AwsObserverScope.enrolled_ecs_services's own validation), and a
    returned `failures[].arn` entry is always the fully-resolved ARN
    form even when a bare name was requested. Reconciling "was this
    requested service actually accounted for" requires comparing both
    sides in the SAME, normalized (bare-name) form."""
    if identifier.startswith("arn:"):
        return identifier.rsplit("/", 1)[-1]
    return identifier


def _parse_services(raw_items: list[dict]) -> tuple[list[EcsServiceObservation], int]:
    parsed: list[EcsServiceObservation] = []
    malformed = 0
    for item in raw_items:
        service_name = item.get("serviceName") if isinstance(item, dict) else None
        cluster_arn = item.get("clusterArn") if isinstance(item, dict) else None
        if not isinstance(service_name, str) or not service_name or not isinstance(cluster_arn, str) or not cluster_arn:
            malformed += 1
            continue
        deployments = item.get("deployments") or []
        rollout_state = None
        for d in deployments:
            if isinstance(d, dict) and d.get("status") == "PRIMARY":
                rollout_state = d.get("rolloutState")
                break
        recent_events = []
        for e in (item.get("events") or [])[:10]:
            if isinstance(e, dict) and e.get("message"):
                recent_events.append(f"{e['message']} @ {_iso(e.get('createdAt')) or 'unknown'}")
        parsed.append(
            EcsServiceObservation(
                cluster_arn=cluster_arn,
                service_name=service_name,
                status=item.get("status"),
                desired_count=item.get("desiredCount"),
                running_count=item.get("runningCount"),
                pending_count=item.get("pendingCount"),
                deployment_rollout_state=rollout_state,
                recent_events=recent_events,
            )
        )
    return parsed, malformed


async def collect_ecs_services(client: AwsClientProtocol) -> tuple[AwsCollectionResult, list[EcsServiceObservation]]:
    scope = client.scope
    if not scope.enrolled_ecs_services and not scope.enrolled_ecs_clusters:
        return (
            _result(AwsCollectionOutcome.EMPTY, "EcsService", scope.account_id, scope.region, "no ECS clusters/services are enrolled for observation"),
            [],
        )

    # Correction round, Issue 2: every bound below applies to the
    # WHOLE run, never merely to one cluster at a time -- a caller
    # enrolling many clusters/services can no longer cause an
    # unbounded number of ListServices pages, resolved (cluster,
    # service) pairs, or DescribeServices batches.
    incomplete_reasons: list[str] = []

    clusters_to_discover = list(scope.enrolled_ecs_clusters)
    if len(clusters_to_discover) > MAX_ECS_CLUSTERS_PER_RUN:
        incomplete_reasons.append(
            f"only {MAX_ECS_CLUSTERS_PER_RUN} of {len(clusters_to_discover)} enrolled clusters were discovered "
            "via ListServices -- the bounded per-run cluster cap was reached"
        )
        clusters_to_discover = clusters_to_discover[:MAX_ECS_CLUSTERS_PER_RUN]

    # Resolve the full (cluster, service) pairs to describe: every
    # explicitly enrolled pair, PLUS (for a bare enrolled cluster, with
    # no specific service named) every service ListServices reports
    # for that cluster -- still never "every cluster in the account",
    # only the explicitly enrolled one(s). Each cluster's own
    # ListServices pagination remains bounded by MAX_PAGES (as
    # before); capping `clusters_to_discover` above additionally
    # bounds the TOTAL ListServices page-fetch count for the whole run
    # to at most `MAX_ECS_CLUSTERS_PER_RUN * MAX_PAGES` -- a concrete,
    # finite ceiling, never "per cluster only".
    pairs: list[tuple[str, str]] = list(scope.enrolled_ecs_services)
    for cluster in clusters_to_discover:
        async def fetch_list_page(token: str | None, _cluster=cluster) -> tuple[list[dict], str | None]:
            body = await client.list_services(_cluster, next_token=token)
            if not isinstance(body, dict) or not isinstance(body.get("serviceArns"), list):
                raise _Malformed("ListServices response had no 'serviceArns' list")
            return body["serviceArns"], body.get("nextToken")

        def parse_arns(raw_items: list) -> tuple[list[str], int]:
            valid = [a for a in raw_items if isinstance(a, str) and a]
            # Correction round, Issue 2: a malformed (non-string/blank)
            # service ARN entry must count toward `malformed_count` --
            # previously silently dropped with malformed_count ALWAYS
            # reported as 0, which could never force PARTIAL no matter
            # how many entries were actually unusable.
            return valid, len(raw_items) - len(valid)

        list_result, service_arns = await _collect("EcsService", scope.account_id, scope.region, fetch_list_page, parse_arns)
        if list_result.outcome not in (AwsCollectionOutcome.SUCCESS, AwsCollectionOutcome.EMPTY, AwsCollectionOutcome.PARTIAL):
            # A hard failure (FORBIDDEN/THROTTLED/UNAVAILABLE/NOT_FOUND)
            # discovering ONE cluster's services still preserves
            # whatever was already resolved from OTHER clusters/
            # explicit pairs, reported as PARTIAL below -- never
            # silently discarding real, already-collected evidence,
            # but also never silently treated as if this cluster had
            # simply had zero services.
            incomplete_reasons.append(f"ListServices for cluster {cluster!r} failed: {list_result.detail}")
            continue
        if list_result.outcome == AwsCollectionOutcome.PARTIAL:
            # THE Issue 2 bug: previously this branch was never taken
            # at all (only a hard-failure outcome short-circuited) --
            # a PARTIAL ListServices collection (e.g. MAX_PAGES reached
            # with a continuation token still present) silently fell
            # through as if it were SUCCESS/EMPTY, discarding the
            # incompleteness before it ever reached the final outcome.
            incomplete_reasons.append(f"ListServices for cluster {cluster!r} was itself incomplete: {list_result.detail}")
        pairs.extend((cluster, arn) for arn in service_arns)

    # Deduplicate -- the same (cluster, service) pair can legitimately
    # appear both via an explicit `enrolled_ecs_services` entry AND via
    # ListServices discovery of its own enrolled cluster; never
    # described (and never counted toward the pair cap) twice.
    seen_pairs: set[tuple[str, str]] = set()
    deduped_pairs: list[tuple[str, str]] = []
    for pair in pairs:
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped_pairs.append(pair)
    pairs = deduped_pairs

    if len(pairs) > MAX_ECS_SERVICE_PAIRS_PER_RUN:
        incomplete_reasons.append(
            f"only {MAX_ECS_SERVICE_PAIRS_PER_RUN} of {len(pairs)} resolved (cluster, service) pairs were "
            "described -- the bounded per-run service-pair cap was reached"
        )
        pairs = pairs[:MAX_ECS_SERVICE_PAIRS_PER_RUN]

    if not pairs:
        if incomplete_reasons:
            return _result(AwsCollectionOutcome.PARTIAL, "EcsService", scope.account_id, scope.region, "; ".join(incomplete_reasons)), []
        return _result(AwsCollectionOutcome.EMPTY, "EcsService", scope.account_id, scope.region, "no ECS services exist for the enrolled cluster(s)"), []

    # Batch DescribeServices by cluster, <=10 service identifiers per
    # call (the real ECS API's own per-call limit) -- bounded to at
    # most MAX_ECS_DESCRIBE_BATCHES_PER_RUN TOTAL batches across every
    # cluster combined, never merely per cluster.
    by_cluster: dict[str, list[str]] = {}
    for cluster, service in pairs:
        by_cluster.setdefault(cluster, []).append(service)

    all_batches: list[tuple[str, list[str]]] = []
    for cluster, services in by_cluster.items():
        for i in range(0, len(services), 10):
            all_batches.append((cluster, services[i : i + 10]))

    if len(all_batches) > MAX_ECS_DESCRIBE_BATCHES_PER_RUN:
        incomplete_reasons.append(
            f"only {MAX_ECS_DESCRIBE_BATCHES_PER_RUN} of {len(all_batches)} DescribeServices batches were "
            "issued -- the bounded per-run batch cap was reached"
        )
        all_batches = all_batches[:MAX_ECS_DESCRIBE_BATCHES_PER_RUN]

    all_observations: list[EcsServiceObservation] = []
    any_partial = bool(incomplete_reasons)
    for cluster, batch in all_batches:
        try:
            body = await client.describe_services(cluster, batch)
        except _RECOGNIZED_FAILURES as exc:
            incomplete_reasons.append(f"DescribeServices for cluster {cluster!r} failed: {exc}")
            any_partial = True
            continue
        if not isinstance(body, dict) or not isinstance(body.get("services"), list):
            incomplete_reasons.append(f"DescribeServices for cluster {cluster!r} returned a malformed/missing response")
            any_partial = True
            continue
        parsed, malformed_count = _parse_services(body["services"])
        all_observations.extend(parsed)
        if malformed_count:
            incomplete_reasons.append(f"{malformed_count} malformed service entry/entries in cluster {cluster!r}'s DescribeServices response")
            any_partial = True
        if body.get("failures"):
            incomplete_reasons.append(f"DescribeServices for cluster {cluster!r} reported {len(body['failures'])} failure(s)")
            any_partial = True

        # Correction round, Issue 2: reconciles every REQUESTED service
        # identifier in this batch against what was actually returned
        # -- `{"services": [], "failures": []}` for a real, enrolled
        # service is NOT a genuine empty result (nothing was ever
        # requested); it means AWS silently returned nothing at all for
        # something this process explicitly asked about, which must
        # never be reported as EMPTY/SUCCESS. Detects three distinct
        # anomalies, each forcing PARTIAL: a requested service missing
        # from BOTH `services` and `failures`; a returned service that
        # was never requested at all; and a duplicated service record.
        requested_bare = {_bare_service_name(s) for s in batch}
        returned_bare = [_bare_service_name(o.service_name) for o in parsed]
        failure_bare = {
            _bare_service_name(str(f.get("arn") or f.get("reason") or ""))
            for f in (body.get("failures") or [])
            if isinstance(f, dict)
        }
        accounted_for = set(returned_bare) | failure_bare

        missing = requested_bare - accounted_for
        if missing:
            incomplete_reasons.append(
                f"cluster {cluster!r}: {len(missing)} requested service(s) ({sorted(missing)}) were not "
                "accounted for in either 'services' or 'failures' -- an incomplete DescribeServices response"
            )
            any_partial = True

        unexpected = set(returned_bare) - requested_bare
        if unexpected:
            incomplete_reasons.append(
                f"cluster {cluster!r}: DescribeServices returned {len(unexpected)} service(s) "
                f"({sorted(unexpected)}) that were never requested"
            )
            any_partial = True

        duplicate_counts = Counter(returned_bare)
        duplicates = sorted(name for name, count in duplicate_counts.items() if count > 1)
        if duplicates:
            incomplete_reasons.append(f"cluster {cluster!r}: duplicate service record(s) returned: {duplicates}")
            any_partial = True

    detail_suffix = f" ({'; '.join(incomplete_reasons)})" if incomplete_reasons else ""
    if any_partial:
        return (
            _result(
                AwsCollectionOutcome.PARTIAL, "EcsService", scope.account_id, scope.region,
                f"{len(all_observations)} service(s) described; collection is INCOMPLETE{detail_suffix}",
                len(all_observations),
            ),
            all_observations,
        )
    if all_observations:
        return _result(AwsCollectionOutcome.SUCCESS, "EcsService", scope.account_id, scope.region, f"{len(all_observations)} service(s) described", len(all_observations)), all_observations
    return _result(AwsCollectionOutcome.EMPTY, "EcsService", scope.account_id, scope.region, "no matching ECS services were returned"), []


# ---------------------------------------------------------------------
# D. CloudTrail management events (supporting evidence only)
# ---------------------------------------------------------------------


def _parse_cloudtrail_events(raw_items: list[dict]) -> tuple[list[CloudTrailEventObservation], int]:
    parsed: list[CloudTrailEventObservation] = []
    malformed = 0
    for item in raw_items:
        event_id = item.get("EventId") if isinstance(item, dict) else None
        event_name = item.get("EventName") if isinstance(item, dict) else None
        if not isinstance(event_id, str) or not event_id or not isinstance(event_name, str) or not event_name:
            malformed += 1
            continue
        resource_names = [
            r.get("ResourceName") for r in (item.get("Resources") or []) if isinstance(r, dict) and r.get("ResourceName")
        ]
        # Deliberately NEVER reads item["CloudTrailEvent"] (the raw,
        # unredacted JSON blob that can carry requestParameters/
        # responseElements/session context) -- see
        # CloudTrailEventObservation's own docstring.
        parsed.append(
            CloudTrailEventObservation(
                event_id=event_id,
                event_name=event_name,
                event_time=_iso(item.get("EventTime")),
                event_source=item.get("EventSource"),
                username=item.get("Username"),
                aws_region=item.get("AwsRegion") if isinstance(item.get("AwsRegion"), str) else None,
                resource_names=[r for r in resource_names if isinstance(r, str)],
            )
        )
    return parsed, malformed


async def collect_cloudtrail_events(client: AwsClientProtocol, *, start_time, end_time) -> tuple[AwsCollectionResult, list[CloudTrailEventObservation]]:
    """`LookupEvents` already returns management events only (data
    events require a separate, un-implemented API) -- bounded to a
    caller-supplied `[start_time, end_time)` window and `MAX_PAGES`
    pages, same discipline as every other collector in this module."""
    scope = client.scope

    async def fetch_page(token: str | None) -> tuple[list[dict], str | None]:
        body = await client.lookup_events(start_time=start_time, end_time=end_time, next_token=token)
        if not isinstance(body, dict) or not isinstance(body.get("Events"), list):
            raise _Malformed("LookupEvents response had no 'Events' list")
        return body["Events"], body.get("NextToken")

    return await _collect("CloudTrailEvent", scope.account_id, scope.region, fetch_page, _parse_cloudtrail_events)
