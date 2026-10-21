"""Correction round (Issues 1 + 2): regression tests proving a
Kubernetes LIST response can never be misrepresented as a complete,
healthy observation when pages remain uncollected, the bounded item
cap is reached, a subsequent page fails, or some items could not be
parsed. Every scenario here must produce `CollectionOutcome.PARTIAL`
(or the correct terminal outcome for a first-page failure) -- never a
false SUCCESS/EMPTY."""

import httpx

from detectors.clients.kubernetes_client import KubernetesClient, MAX_ITEMS
from detectors.kubernetes.collector import collect_pods
from detectors.schemas.kubernetes import CollectionOutcome


def _client(handler) -> KubernetesClient:
    return KubernetesClient("https://k8s.invalid:6443", "reliability-sandbox", transport=httpx.MockTransport(handler))


def _pod(name: str) -> dict:
    return {
        "metadata": {"name": name, "namespace": "reliability-sandbox", "uid": "u-1"},
        "spec": {"nodeName": "node-1"},
        "status": {"phase": "Running", "containerStatuses": []},
    }


def _malformed_pod() -> dict:
    # Missing the required "metadata" entirely -- parser must skip it.
    return {"status": {"phase": "Running"}}


# ---------------------------------------------------------------------
# Issue 1: pagination / continuation-token handling
# ---------------------------------------------------------------------


async def test_empty_first_page_with_continuation_token_is_never_reported_empty():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.query.decode())
        if "continue=" not in request.url.query.decode():
            return httpx.Response(200, json={"metadata": {"continue": "tok-1"}, "items": []})
        return httpx.Response(200, json={"metadata": {}, "items": [_pod("page2-pod")]})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.SUCCESS
    assert result.items_count == 1
    assert len(items) == 1
    assert len(calls) == 2  # the continuation page was actually followed


async def test_nonempty_first_page_with_continuation_token_follows_the_next_page():
    def handler(request: httpx.Request) -> httpx.Response:
        if "continue=" not in request.url.query.decode():
            return httpx.Response(200, json={"metadata": {"continue": "tok-1"}, "items": [_pod("page1-pod")]})
        return httpx.Response(200, json={"metadata": {}, "items": [_pod("page2-pod")]})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.SUCCESS
    assert result.items_count == 2
    assert {i.name for i in items} == {"page1-pod", "page2-pod"}


async def test_fully_completed_list_with_no_continuation_token_is_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"metadata": {}, "items": [_pod("only-pod")]})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.SUCCESS
    assert result.items_count == 1


async def test_item_cap_exceeded_with_continuation_remaining_is_partial_not_success():
    huge_page = [_pod(f"pod-{i}") for i in range(MAX_ITEMS)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"metadata": {"continue": "more-pages-exist"}, "items": huge_page})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.PARTIAL
    assert result.items_count == MAX_ITEMS
    assert "cap" in result.detail.lower()


async def test_single_page_exceeding_cap_with_no_continuation_is_still_partial():
    """Defensive: a non-compliant server ignores `limit=` and returns
    more than MAX_ITEMS in one page -- client-side truncation must
    still be disclosed, never silently treated as a complete SUCCESS."""
    huge_page = [_pod(f"pod-{i}") for i in range(MAX_ITEMS + 50)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"metadata": {}, "items": huge_page})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.PARTIAL
    assert result.items_count <= MAX_ITEMS
    assert len(items) <= MAX_ITEMS


async def test_subsequent_page_forbidden_preserves_first_page_evidence_as_partial():
    def handler(request: httpx.Request) -> httpx.Response:
        if "continue=" not in request.url.query.decode():
            return httpx.Response(200, json={"metadata": {"continue": "tok-1"}, "items": [_pod("page1-pod")]})
        return httpx.Response(403, json={"message": "forbidden"})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.PARTIAL
    assert result.items_count == 1
    assert len(items) == 1  # the first page's real evidence is preserved, never discarded
    assert "forbidden" in result.detail.lower()


async def test_subsequent_page_connection_failure_preserves_first_page_evidence_as_partial():
    def handler(request: httpx.Request) -> httpx.Response:
        if "continue=" not in request.url.query.decode():
            return httpx.Response(200, json={"metadata": {"continue": "tok-1"}, "items": [_pod("page1-pod")]})
        raise httpx.ConnectError("refused", request=request)

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.PARTIAL
    assert result.items_count == 1


async def test_first_page_forbidden_is_still_forbidden_not_partial():
    """A first-page failure keeps its original, specific outcome --
    PARTIAL is reserved for when SOME real evidence was collected."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.FORBIDDEN
    assert items == []


async def test_page_fetch_limit_bound_prevents_an_unbounded_pagination_loop():
    """An adversarial/buggy server that always returns a continuation
    token must never cause an unbounded number of requests."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"metadata": {"continue": "keep-going"}, "items": []})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.PARTIAL
    assert call_count["n"] <= 10  # bounded, never infinite


# ---------------------------------------------------------------------
# Issue 2: malformed items on an otherwise-200 response
# ---------------------------------------------------------------------


async def test_all_items_malformed_on_a_200_response_is_never_success_or_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_malformed_pod(), _malformed_pod()]})

    result, items = await collect_pods(_client(handler))
    assert result.outcome not in (CollectionOutcome.SUCCESS, CollectionOutcome.EMPTY)
    assert result.outcome == CollectionOutcome.PARTIAL
    assert result.items_count == 0
    assert items == []


async def test_mixed_valid_and_malformed_items_discloses_partial_coverage():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_pod("good-pod"), _malformed_pod()]})

    result, items = await collect_pods(_client(handler))
    assert result.outcome == CollectionOutcome.PARTIAL
    assert result.items_count == 1
    assert len(items) == 1
    assert items[0].name == "good-pod"  # the valid item's evidence is preserved
