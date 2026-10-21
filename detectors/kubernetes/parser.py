"""Gate B (Phase 12A): defensive parsing of raw Kubernetes API JSON
into the typed observation models in `detectors.schemas.kubernetes`.

Same discipline as `detectors/traces/parser.py`: every nested field is
explicitly type-checked before use, nothing here ever raises on
malformed input (a malformed item is simply skipped and counted), and
nothing here ever invents a value that was not actually present in
the response."""

from detectors.schemas.kubernetes import (
    ContainerResourceLimits,
    ContainerStatusObservation,
    ContainerTerminatedState,
    ContainerWaitingState,
    DeploymentConditionObservation,
    DeploymentObservation,
    EventObservation,
    PodConditionObservation,
    PodObservation,
    ReplicaSetObservation,
)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _parse_terminated(t: dict) -> ContainerTerminatedState:
    return ContainerTerminatedState(
        reason=_str_or_none(t.get("reason")),
        exit_code=_int_or_none(t.get("exitCode")),
        started_at=_str_or_none(t.get("startedAt")),
        finished_at=_str_or_none(t.get("finishedAt")),
        message=_str_or_none(t.get("message")),
    )


def _parse_container_status(cs: dict) -> ContainerStatusObservation | None:
    name = _str_or_none(cs.get("name"))
    if name is None:
        return None

    state = cs.get("state") if isinstance(cs.get("state"), dict) else {}
    waiting = None
    running = False
    terminated = None
    if isinstance(state.get("waiting"), dict):
        w = state["waiting"]
        waiting = ContainerWaitingState(reason=_str_or_none(w.get("reason")), message=_str_or_none(w.get("message")))
    if isinstance(state.get("running"), dict):
        running = True
    if isinstance(state.get("terminated"), dict):
        terminated = _parse_terminated(state["terminated"])

    last_state = cs.get("lastState") if isinstance(cs.get("lastState"), dict) else {}
    last_terminated = None
    if isinstance(last_state.get("terminated"), dict):
        last_terminated = _parse_terminated(last_state["terminated"])

    limits = None
    resources = cs.get("resources") if isinstance(cs.get("resources"), dict) else {}
    raw_limits = resources.get("limits") if isinstance(resources.get("limits"), dict) else None
    if isinstance(raw_limits, dict):
        limits = ContainerResourceLimits(cpu=_str_or_none(raw_limits.get("cpu")), memory=_str_or_none(raw_limits.get("memory")))

    return ContainerStatusObservation(
        container_name=name,
        image=_str_or_none(cs.get("image")),
        ready=_bool_or_none(cs.get("ready")),
        restart_count=_int_or_none(cs.get("restartCount")),
        waiting=waiting,
        running=running,
        terminated=terminated,
        last_terminated=last_terminated,
        limits=limits,
    )


def parse_pod(item: object) -> PodObservation | None:
    """Returns None (never raises) for anything this cannot safely
    interpret as a pod."""
    try:
        if not isinstance(item, dict):
            return None
        metadata = item.get("metadata")
        spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        if not isinstance(metadata, dict):
            return None
        name = _str_or_none(metadata.get("name"))
        namespace = _str_or_none(metadata.get("namespace"))
        if name is None or namespace is None:
            return None

        owner_kind = owner_name = None
        owner_refs = metadata.get("ownerReferences")
        if isinstance(owner_refs, list) and owner_refs and isinstance(owner_refs[0], dict):
            owner_kind = _str_or_none(owner_refs[0].get("kind"))
            owner_name = _str_or_none(owner_refs[0].get("name"))

        container_statuses = []
        raw_cs = status.get("containerStatuses")
        if isinstance(raw_cs, list):
            for cs in raw_cs:
                if isinstance(cs, dict):
                    parsed = _parse_container_status(cs)
                    if parsed is not None:
                        container_statuses.append(parsed)

        conditions = []
        raw_conditions = status.get("conditions")
        if isinstance(raw_conditions, list):
            for c in raw_conditions:
                if isinstance(c, dict):
                    conditions.append(
                        PodConditionObservation(
                            type=_str_or_none(c.get("type")),
                            status=_str_or_none(c.get("status")),
                            reason=_str_or_none(c.get("reason")),
                            message=_str_or_none(c.get("message")),
                            last_transition_time=_str_or_none(c.get("lastTransitionTime")),
                        )
                    )

        return PodObservation(
            namespace=namespace,
            name=name,
            uid=_str_or_none(metadata.get("uid")),
            phase=_str_or_none(status.get("phase")),
            node_name=_str_or_none(spec.get("nodeName")),
            owner_kind=owner_kind,
            owner_name=owner_name,
            container_statuses=container_statuses,
            conditions=conditions,
            creation_timestamp=_str_or_none(metadata.get("creationTimestamp")),
        )
    except Exception:
        return None


def parse_pods(items: list) -> tuple[list[PodObservation], int]:
    parsed = []
    malformed = 0
    for item in items:
        p = parse_pod(item)
        if p is None:
            malformed += 1
        else:
            parsed.append(p)
    return parsed, malformed


def parse_deployment(item: object) -> DeploymentObservation | None:
    try:
        if not isinstance(item, dict):
            return None
        metadata = item.get("metadata")
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        if not isinstance(metadata, dict):
            return None
        name = _str_or_none(metadata.get("name"))
        namespace = _str_or_none(metadata.get("namespace"))
        if name is None or namespace is None:
            return None

        conditions = []
        raw_conditions = status.get("conditions")
        if isinstance(raw_conditions, list):
            for c in raw_conditions:
                if isinstance(c, dict):
                    conditions.append(
                        DeploymentConditionObservation(
                            type=_str_or_none(c.get("type")),
                            status=_str_or_none(c.get("status")),
                            reason=_str_or_none(c.get("reason")),
                            message=_str_or_none(c.get("message")),
                            last_update_time=_str_or_none(c.get("lastUpdateTime")),
                            last_transition_time=_str_or_none(c.get("lastTransitionTime")),
                        )
                    )

        return DeploymentObservation(
            namespace=namespace,
            name=name,
            uid=_str_or_none(metadata.get("uid")),
            generation=_int_or_none(metadata.get("generation")),
            observed_generation=_int_or_none(status.get("observedGeneration")),
            replicas=_int_or_none(status.get("replicas")),
            ready_replicas=_int_or_none(status.get("readyReplicas")),
            available_replicas=_int_or_none(status.get("availableReplicas")),
            updated_replicas=_int_or_none(status.get("updatedReplicas")),
            unavailable_replicas=_int_or_none(status.get("unavailableReplicas")),
            conditions=conditions,
        )
    except Exception:
        return None


def parse_deployments(items: list) -> tuple[list[DeploymentObservation], int]:
    parsed = []
    malformed = 0
    for item in items:
        d = parse_deployment(item)
        if d is None:
            malformed += 1
        else:
            parsed.append(d)
    return parsed, malformed


def parse_replicaset(item: object) -> ReplicaSetObservation | None:
    try:
        if not isinstance(item, dict):
            return None
        metadata = item.get("metadata")
        status = item.get("status") if isinstance(item.get("status"), dict) else {}
        if not isinstance(metadata, dict):
            return None
        name = _str_or_none(metadata.get("name"))
        namespace = _str_or_none(metadata.get("namespace"))
        if name is None or namespace is None:
            return None

        owner_name = None
        owner_refs = metadata.get("ownerReferences")
        if isinstance(owner_refs, list) and owner_refs and isinstance(owner_refs[0], dict):
            owner_name = _str_or_none(owner_refs[0].get("name"))

        annotations = metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
        revision = _str_or_none(annotations.get("deployment.kubernetes.io/revision"))

        return ReplicaSetObservation(
            namespace=namespace,
            name=name,
            uid=_str_or_none(metadata.get("uid")),
            owner_name=owner_name,
            replicas=_int_or_none(status.get("replicas")),
            ready_replicas=_int_or_none(status.get("readyReplicas")),
            revision=revision,
        )
    except Exception:
        return None


def parse_replicasets(items: list) -> tuple[list[ReplicaSetObservation], int]:
    parsed = []
    malformed = 0
    for item in items:
        r = parse_replicaset(item)
        if r is None:
            malformed += 1
        else:
            parsed.append(r)
    return parsed, malformed


def parse_event(item: object) -> EventObservation | None:
    try:
        if not isinstance(item, dict):
            return None
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        involved = item.get("involvedObject") if isinstance(item.get("involvedObject"), dict) else {}
        namespace = _str_or_none(metadata.get("namespace"))
        if namespace is None:
            return None

        return EventObservation(
            namespace=namespace,
            involved_object_kind=_str_or_none(involved.get("kind")),
            involved_object_name=_str_or_none(involved.get("name")),
            reason=_str_or_none(item.get("reason")),
            message=_str_or_none(item.get("message")),
            type=_str_or_none(item.get("type")),
            count=_int_or_none(item.get("count")),
            first_timestamp=_str_or_none(item.get("firstTimestamp")),
            last_timestamp=_str_or_none(item.get("lastTimestamp")),
        )
    except Exception:
        return None


def parse_events(items: list) -> tuple[list[EventObservation], int]:
    parsed = []
    malformed = 0
    for item in items:
        e = parse_event(item)
        if e is None:
            malformed += 1
        else:
            parsed.append(e)
    return parsed, malformed
