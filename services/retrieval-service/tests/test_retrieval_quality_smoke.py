"""Phase 6 §18: a small, deterministic retrieval-quality smoke test
against the REAL source-controlled runbooks, using the deterministic
LOCAL lexical embedding provider only (no network, no real DB --
pure in-memory ranking over the real knowledge/runbooks/*.md files).

This does NOT prove semantic retrieval quality -- the local provider
is lexical, not a neural/semantic model (see embeddings/provider.py's
own docstring). It only verifies the deterministic retrieval pipeline
(load -> chunk -> embed -> rank) and its ranking contract: a query
whose vocabulary clearly overlaps with one specific runbook should
find that runbook within a small, bounded top-K.

The knowledge root resolves two ways, so this runs correctly both
locally (direct pytest, relative path from this repo's own layout)
and in the Docker-isolated `make retrieval-test` container (which
bind-mounts knowledge/ at /knowledge and sets
RETRIEVAL_TEST_KNOWLEDGE_ROOT accordingly -- see the Makefile).
"""

import math
import os
import pathlib

import pytest

from retrieval_service.chunking import chunk_text
from retrieval_service.embeddings.provider import LocalLexicalEmbeddingProvider
from retrieval_service.knowledge import load_knowledge_documents

_TOP_K = 5


def _knowledge_root() -> pathlib.Path:
    """Resolves to the "knowledge" directory itself (the PARENT of
    runbooks/) -- matching exactly what RETRIEVAL_KNOWLEDGE_ROOT points
    at in the real deployment (docker-compose.yml mounts
    ./knowledge:/knowledge:ro), so source_key values here
    ("runbooks/checkout-server-errors.md", etc.) match the real
    indexed corpus's own source_key values byte-for-byte."""
    env_root = os.environ.get("RETRIEVAL_TEST_KNOWLEDGE_ROOT")
    if env_root:
        return pathlib.Path(env_root)
    # services/retrieval-service/tests/this_file.py -> repo root is
    # three parents up from the "tests" directory -- but inside the
    # Docker-isolated test container (no RETRIEVAL_TEST_KNOWLEDGE_ROOT
    # set), only /app/tests and /app exist above this file, so this
    # index is simply out of range; fall back to a sentinel path that
    # `load_knowledge_documents` (and this module's own fixture) both
    # treat as "not found" -> skip, never a crash.
    here = pathlib.Path(__file__).resolve()
    parents = here.parents
    if len(parents) <= 3:
        return pathlib.Path("/nonexistent-knowledge-root")
    return parents[3] / "knowledge"


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.fixture(scope="module")
def indexed_chunks():
    root = _knowledge_root()
    docs = load_knowledge_documents(str(root))
    if not docs:
        pytest.skip(f"real knowledge/runbooks corpus not found at {root}")

    provider = LocalLexicalEmbeddingProvider()
    chunks = []

    async def build():
        import asyncio

        for doc in docs:
            pieces = chunk_text(doc.text, max_chars=1200, overlap_chars=150)
            embeddings = await provider.embed(pieces)
            for text, embedding in zip(pieces, embeddings, strict=True):
                chunks.append((doc.source_key, text, embedding))

    import asyncio

    asyncio.run(build())
    return provider, chunks


def _top_k_sources(provider, chunks, query: str, k: int = _TOP_K) -> list[str]:
    import asyncio

    [query_vec] = asyncio.run(provider.embed([query]))
    ranked = sorted(chunks, key=lambda c: -_cosine(c[2], query_vec))
    return [source_key for source_key, _text, _vec in ranked[:k]]


@pytest.mark.parametrize(
    ("query", "expected_runbook"),
    [
        ("checkout 5xx payment dependency unavailable", "runbooks/checkout-server-errors.md"),
        ("checkout latency", "runbooks/checkout-high-latency.md"),
        ("telemetry collector unavailable", "runbooks/telemetry-pipeline-unavailable.md"),
        ("collector refusing telemetry", "runbooks/collector-refusing-telemetry.md"),
    ],
)
def test_known_query_retrieves_its_expected_runbook_within_bounded_top_k(indexed_chunks, query, expected_runbook):
    provider, chunks = indexed_chunks
    top_sources = _top_k_sources(provider, chunks, query)
    assert expected_runbook in top_sources, (
        f"query {query!r} did not retrieve {expected_runbook!r} within the top {_TOP_K} "
        f"(got {top_sources}) -- this only checks the deterministic lexical pipeline's own "
        "ranking contract, not semantic retrieval quality"
    )


def test_all_four_real_runbooks_are_present_in_the_corpus(indexed_chunks):
    _provider, chunks = indexed_chunks
    source_keys = {c[0] for c in chunks}
    for expected in (
        "runbooks/checkout-server-errors.md",
        "runbooks/checkout-high-latency.md",
        "runbooks/telemetry-pipeline-unavailable.md",
        "runbooks/collector-refusing-telemetry.md",
    ):
        assert expected in source_keys
