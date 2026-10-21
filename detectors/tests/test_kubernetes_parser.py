"""Gate B (Phase 12A): defensive parsing tests -- malformed Kubernetes
API JSON must never crash the parser, and must never fabricate a
field that was not actually present."""

from detectors.kubernetes.parser import (
    parse_deployment,
    parse_deployments,
    parse_event,
    parse_pod,
    parse_pods,
    parse_replicaset,
)


def _pod(name="pod-a", namespace="reliability-sandbox", container_statuses=None, conditions=None, phase="Running", owner=None):
    return {
        "metadata": {
            "name": name,
            "namespace": namespace,
            "uid": "uid-1",
            "creationTimestamp": "2026-10-20T00:00:00Z",
            **({"ownerReferences": [{"kind": owner[0], "name": owner[1]}]} if owner else {}),
        },
        "spec": {"nodeName": "node-1"},
        "status": {
            "phase": phase,
            "containerStatuses": container_statuses or [],
            "conditions": conditions or [],
        },
    }


def test_parse_valid_running_pod():
    item = _pod(container_statuses=[{"name": "app", "image": "nginx", "ready": True, "restartCount": 0, "state": {"running": {}}}])
    pod = parse_pod(item)
    assert pod is not None
    assert pod.name == "pod-a"
    assert pod.container_statuses[0].running is True
    assert pod.container_statuses[0].ready is True


def test_parse_pod_with_waiting_and_terminated_and_last_state():
    item = _pod(
        container_statuses=[
            {
                "name": "app",
                "image": "myapp:v1",
                "ready": False,
                "restartCount": 5,
                "state": {"waiting": {"reason": "CrashLoopBackOff", "message": "back-off restarting failed container"}},
                "lastState": {"terminated": {"reason": "Error", "exitCode": 1, "startedAt": "2026-10-20T00:00:00Z", "finishedAt": "2026-10-20T00:00:05Z"}},
                "resources": {"limits": {"cpu": "100m", "memory": "64Mi"}},
            }
        ]
    )
    pod = parse_pod(item)
    cs = pod.container_statuses[0]
    assert cs.waiting.reason == "CrashLoopBackOff"
    assert cs.last_terminated.reason == "Error"
    assert cs.last_terminated.exit_code == 1
    assert cs.limits.memory == "64Mi"
    assert cs.terminated is None


def test_parse_pod_missing_termination_data_is_none_not_fabricated():
    item = _pod(container_statuses=[{"name": "app", "restartCount": 3, "state": {"waiting": {"reason": "CrashLoopBackOff"}}}])
    pod = parse_pod(item)
    cs = pod.container_statuses[0]
    assert cs.terminated is None
    assert cs.last_terminated is None
    assert cs.limits is None


def test_parse_pod_with_owner_reference():
    item = _pod(owner=("ReplicaSet", "myapp-abc123"))
    pod = parse_pod(item)
    assert pod.owner_kind == "ReplicaSet"
    assert pod.owner_name == "myapp-abc123"


def test_parse_rejects_non_dict_item():
    assert parse_pod("not-a-dict") is None
    assert parse_pod(None) is None
    assert parse_pod(["list"]) is None


def test_parse_rejects_item_missing_required_identity_fields():
    assert parse_pod({"metadata": {"name": "only-name"}}) is None  # missing namespace
    assert parse_pod({"metadata": {}}) is None


def test_parse_pods_batch_counts_malformed_separately_from_valid():
    items = [_pod(name="good-1"), "not-a-pod", _pod(name="good-2"), {"metadata": {}}]
    parsed, malformed = parse_pods(items)
    assert len(parsed) == 2
    assert malformed == 2
    assert {p.name for p in parsed} == {"good-1", "good-2"}


def test_parse_malformed_container_status_entries_are_skipped_not_crashed():
    item = _pod(container_statuses=["not-a-dict", {"name": "app", "state": {}}, 42])
    pod = parse_pod(item)
    assert pod is not None
    assert len(pod.container_statuses) == 1
    assert pod.container_statuses[0].container_name == "app"


def test_parse_container_status_with_unknown_waiting_reason_still_parses():
    """An unrecognized waiting.reason string must still parse cleanly
    -- classification (not parsing) is where 'known vs unknown reason'
    is decided."""
    item = _pod(container_statuses=[{"name": "app", "state": {"waiting": {"reason": "SomeBrandNewReasonNeverSeenBefore"}}}])
    pod = parse_pod(item)
    assert pod.container_statuses[0].waiting.reason == "SomeBrandNewReasonNeverSeenBefore"


def test_parse_malformed_top_level_body_never_raises():
    assert parse_pod({"metadata": "not-a-dict"}) is None
    assert parse_pod({"metadata": {"name": "x", "namespace": "y"}, "status": "not-a-dict"}) is not None  # status defaults to {}


def test_parse_deployment_with_conditions():
    item = {
        "metadata": {"name": "my-deploy", "namespace": "reliability-sandbox", "uid": "u-1", "generation": 3},
        "status": {
            "observedGeneration": 3,
            "replicas": 2,
            "readyReplicas": 2,
            "availableReplicas": 2,
            "updatedReplicas": 2,
            "conditions": [
                {"type": "Available", "status": "True", "reason": "MinimumReplicasAvailable"},
                {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable"},
            ],
        },
    }
    d = parse_deployment(item)
    assert d.generation == 3
    assert d.observed_generation == 3
    assert len(d.conditions) == 2


def test_parse_deployment_missing_status_fields_are_none():
    item = {"metadata": {"name": "my-deploy", "namespace": "reliability-sandbox"}}
    d = parse_deployment(item)
    assert d is not None
    assert d.replicas is None
    assert d.conditions == []


def test_parse_deployments_batch_counts_malformed():
    items = [{"metadata": {"name": "a", "namespace": "ns"}}, "garbage", None]
    parsed, malformed = parse_deployments(items)
    assert len(parsed) == 1
    assert malformed == 2


def test_parse_replicaset_with_revision_annotation():
    item = {
        "metadata": {
            "name": "my-deploy-abc123",
            "namespace": "reliability-sandbox",
            "ownerReferences": [{"kind": "Deployment", "name": "my-deploy"}],
            "annotations": {"deployment.kubernetes.io/revision": "7"},
        },
        "status": {"replicas": 2, "readyReplicas": 2},
    }
    rs = parse_replicaset(item)
    assert rs.owner_name == "my-deploy"
    assert rs.revision == "7"


def test_parse_event_with_involved_object():
    item = {
        "metadata": {"namespace": "reliability-sandbox"},
        "involvedObject": {"kind": "Pod", "name": "pod-a"},
        "reason": "BackOff",
        "message": "Back-off restarting failed container",
        "type": "Warning",
        "count": 5,
        "firstTimestamp": "2026-10-20T00:00:00Z",
        "lastTimestamp": "2026-10-20T00:05:00Z",
    }
    e = parse_event(item)
    assert e.involved_object_name == "pod-a"
    assert e.reason == "BackOff"
    assert e.count == 5


def test_parse_event_missing_namespace_is_none():
    assert parse_event({"involvedObject": {"kind": "Pod", "name": "pod-a"}}) is None
