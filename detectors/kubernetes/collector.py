"""Gate B (Phase 12A): ties `KubernetesClient` (transport) and
`detectors.kubernetes.parser` (shape validation) together, producing
one `CollectionResult` + a typed item list per resource kind -- the
single place that decides which `CollectionOutcome` a given sequence
of (status_code, body) pairs represents. Mirrors
`detectors.pipeline.orchestrator`'s own per-check try/except pattern:
one unavailable source is recorded, never raised past this layer, and
never allowed to look like a healthy/empty result.

Correction round (Issues 1 + 2): a Kubernetes LIST response can be
paginated (`metadata.continue`) and can contain items this process
cannot parse. Both were previously collapsed into SUCCESS/EMPTY,
which could silently misrepresent an incomplete observation as a
complete, healthy one. This module now follows continuation pages up
to a small, fixed bound (`_MAX_PAGES`) and reports `PARTIAL` -- never
SUCCESS or EMPTY -- whenever real evidence is incomplete: a
continuation page remains uncollected, the bounded item/page cap was
reached while more pages existed, a later page failed/was forbidden,
or some items on an otherwise-successful page could not be parsed.
Already-collected items are always preserved and returned, never
discarded, so a caller can still use whatever real evidence exists."""

from detectors.clients.kubernetes_client import KubernetesClient, KubernetesUnavailableError, MAX_ITEMS
from detectors.kubernetes.parser import parse_deployments, parse_events, parse_pods, parse_replicasets
from detectors.schemas.kubernetes import (
    CollectionOutcome,
    CollectionResult,
    DeploymentObservation,
    EventObservation,
    PodObservation,
    ReplicaSetObservation,
)

# A small, fixed bound on how many continuation pages this collector
# will follow for one resource kind in one observation cycle -- "bounded
# pagination," never an open-ended loop. Each page itself already
# requests `limit=MAX_ITEMS`, so a compliant API server needs at most
# one or two pages in practice; this is a defensive ceiling for a
# server that ignores that hint or returns unexpectedly small pages.
_MAX_PAGES = 5


def _partial(resource_kind: str, namespace: str, accumulated: list, malformed_total: int, reason: str) -> tuple[CollectionResult, list]:
    detail = f"{len(accumulated)} item(s) collected and preserved, but collection is INCOMPLETE: {reason}"
    if malformed_total:
        detail += f"; additionally {malformed_total} item(s) across the collected page(s) could not be parsed and were skipped"
    return (
        CollectionResult(
            outcome=CollectionOutcome.PARTIAL, resource_kind=resource_kind, namespace=namespace,
            detail=detail, items_count=len(accumulated),
        ),
        accumulated,
    )


def _unavailable(resource_kind: str, namespace: str, reason: str) -> tuple[CollectionResult, list]:
    return (
        CollectionResult(
            outcome=CollectionOutcome.UNAVAILABLE, resource_kind=resource_kind, namespace=namespace, detail=reason
        ),
        [],
    )


async def _collect_paginated(resource_kind: str, namespace: str, list_fn, parse_fn) -> tuple[CollectionResult, list]:
    accumulated: list = []
    malformed_total = 0
    continue_token: str | None = None
    pages_fetched = 0

    while True:
        try:
            status_code, body = await list_fn(continue_token=continue_token)
        except KubernetesUnavailableError as exc:
            if pages_fetched == 0:
                return _unavailable(resource_kind, namespace, str(exc))
            return _partial(resource_kind, namespace, accumulated, malformed_total, f"a subsequent page could not be fetched: {exc}")

        pages_fetched += 1

        if status_code == 403:
            if pages_fetched == 1:
                return (
                    CollectionResult(
                        outcome=CollectionOutcome.FORBIDDEN, resource_kind=resource_kind, namespace=namespace,
                        detail="the Kubernetes API server returned HTTP 403 Forbidden for this request (RBAC)",
                    ),
                    [],
                )
            return _partial(resource_kind, namespace, accumulated, malformed_total, "a subsequent page was forbidden (RBAC)")

        if status_code == 404:
            if pages_fetched == 1:
                return (
                    CollectionResult(
                        outcome=CollectionOutcome.NOT_FOUND, resource_kind=resource_kind, namespace=namespace,
                        detail="the Kubernetes API server returned HTTP 404 Not Found for this request",
                    ),
                    [],
                )
            return _partial(resource_kind, namespace, accumulated, malformed_total, "a subsequent page returned HTTP 404 Not Found")

        if not isinstance(body, dict):
            if pages_fetched == 1:
                return (
                    CollectionResult(
                        outcome=CollectionOutcome.MALFORMED, resource_kind=resource_kind, namespace=namespace,
                        detail="response body was not a JSON object",
                    ),
                    [],
                )
            return _partial(resource_kind, namespace, accumulated, malformed_total, "a subsequent page's response body was not a JSON object")

        raw_items = body.get("items")
        if not isinstance(raw_items, list):
            if pages_fetched == 1:
                return (
                    CollectionResult(
                        outcome=CollectionOutcome.MALFORMED, resource_kind=resource_kind, namespace=namespace,
                        detail="response body had no 'items' list",
                    ),
                    [],
                )
            return _partial(resource_kind, namespace, accumulated, malformed_total, "a subsequent page's response body had no 'items' list")

        remaining_capacity = MAX_ITEMS - len(accumulated)
        page_items = raw_items[:remaining_capacity]
        page_was_truncated = len(raw_items) > len(page_items)  # the server returned more in ONE page than our remaining cap allows

        parsed, malformed_count = parse_fn(page_items)
        accumulated.extend(parsed)
        malformed_total += malformed_count

        metadata = body.get("metadata")
        next_continue = metadata.get("continue") if isinstance(metadata, dict) else None
        if not isinstance(next_continue, str) or not next_continue:
            next_continue = None

        if len(accumulated) >= MAX_ITEMS and (next_continue or page_was_truncated):
            return _partial(
                resource_kind, namespace, accumulated, malformed_total,
                f"the bounded item cap ({MAX_ITEMS}) was reached while additional page(s) remained uncollected",
            )

        if next_continue is None:
            # No more continuation pages remain -- this IS the complete
            # result, but malformed items still disqualify it from ever
            # being reported as a clean SUCCESS/EMPTY (Issue 2).
            if malformed_total > 0:
                detail = (
                    f"{len(accumulated)} item(s) parsed successfully"
                    + (f" across {pages_fetched} page(s)" if pages_fetched > 1 else "")
                    + f"; {malformed_total} item(s) could not be parsed and were skipped -- never a clean healthy result"
                )
                return (
                    CollectionResult(
                        outcome=CollectionOutcome.PARTIAL, resource_kind=resource_kind, namespace=namespace,
                        detail=detail, items_count=len(accumulated),
                    ),
                    accumulated,
                )
            if accumulated:
                detail = f"{len(accumulated)} item(s) parsed successfully"
                if pages_fetched > 1:
                    detail += f" across {pages_fetched} page(s)"
                return (
                    CollectionResult(
                        outcome=CollectionOutcome.SUCCESS, resource_kind=resource_kind, namespace=namespace,
                        detail=detail, items_count=len(accumulated),
                    ),
                    accumulated,
                )
            return (
                CollectionResult(
                    outcome=CollectionOutcome.EMPTY, resource_kind=resource_kind, namespace=namespace,
                    detail="the API call succeeded; zero items were returned", items_count=0,
                ),
                [],
            )

        if pages_fetched >= _MAX_PAGES:
            return _partial(
                resource_kind, namespace, accumulated, malformed_total,
                f"the bounded page-fetch limit ({_MAX_PAGES} pages) was reached while continuation pages remained",
            )

        continue_token = next_continue
        # loop: fetch the next page with `continue_token`


async def collect_pods(client: KubernetesClient) -> tuple[CollectionResult, list[PodObservation]]:
    return await _collect_paginated("Pod", client.namespace, client.list_pods, parse_pods)


async def collect_deployments(client: KubernetesClient) -> tuple[CollectionResult, list[DeploymentObservation]]:
    return await _collect_paginated("Deployment", client.namespace, client.list_deployments, parse_deployments)


async def collect_replicasets(client: KubernetesClient) -> tuple[CollectionResult, list[ReplicaSetObservation]]:
    return await _collect_paginated("ReplicaSet", client.namespace, client.list_replicasets, parse_replicasets)


async def collect_events(client: KubernetesClient) -> tuple[CollectionResult, list[EventObservation]]:
    return await _collect_paginated("Event", client.namespace, client.list_events, parse_events)
