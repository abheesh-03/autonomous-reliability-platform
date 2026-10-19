"""Retrieval-relevance scoring -- Gate C requirement B.

Reuses retrieval-service's REAL, production, deterministic pipeline
directly over the REAL, source-controlled `knowledge/runbooks/*.md`
corpus (never a reimplementation, never a synthetic corpus):

  - `retrieval_service.knowledge.load_knowledge_documents` loads the
    real runbooks.
  - `retrieval_service.chunking.chunk_text` chunks them exactly as the
    real offline indexer (`python -m retrieval_service.indexer`) does.
  - `retrieval_service.embeddings.provider.LocalLexicalEmbeddingProvider`
    is the SAME deterministic, offline, lexical embedding provider
    `tests/test_retrieval_quality_smoke.py` already uses for its own
    proven ranking-contract smoke test -- no network call, no paid
    API, exact same vector for the exact same text on any machine.

This proves the deterministic lexical ranking CONTRACT (a query whose
vocabulary overlaps a specific runbook finds it within a bounded
top-k) -- it does NOT prove semantic retrieval quality, which is a
property of whichever embedding model is actually configured in
production (OpenAIEmbeddingProvider), never of this lexical stand-in.
See evals/README.md's "what Phase 10 does not prove" section.

A case's `input` is a dict with:
  - "query": str
  - "relevant_source_keys": list[str] -- real runbook source_key
    values (e.g. "runbooks/checkout-server-errors.md") this query is
    genuinely about, per the case's own ground-truth rationale. May be
    empty (a query that is not genuinely about any of the four real
    runbooks).

A case's `expected_outcome`:
  - "top_k": int
  - "require_hit": bool -- whether at least one of
    `relevant_source_keys` MUST appear in the top-k ranked results
    (true for a genuinely relevant query; false for a query this
    case's ground truth says should NOT retrieve that runbook within
    top-k -- proving the ranking engine does not conflate unrelated
    runbooks, and that this harness can correctly detect a miss, not
    only a hit).
"""

import pathlib

from retrieval_service.chunking import chunk_text
from retrieval_service.embeddings.provider import LocalLexicalEmbeddingProvider
from retrieval_service.knowledge import load_knowledge_documents

from evals.scoring.models import Case, CaseResult, Result

_KNOWLEDGE_ROOT_ENV = "EVALS_KNOWLEDGE_ROOT"


def _knowledge_root() -> pathlib.Path:
    import os

    env_root = os.environ.get(_KNOWLEDGE_ROOT_ENV)
    if env_root:
        return pathlib.Path(env_root)
    # evals/scoring/retrieval.py -> repo root is two parents up from
    # "evals" -- matches knowledge/ at the repo root exactly like
    # retrieval-service's own test_retrieval_quality_smoke.py resolves
    # it relative to ITS OWN file location.
    here = pathlib.Path(__file__).resolve()
    return here.parents[2] / "knowledge"


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


_INDEX_CACHE: dict[str, list[tuple[str, list[float]]]] = {}


async def _indexed_chunks() -> list[tuple[str, list[float]]]:
    """Built once per process and cached -- re-chunking/re-embedding
    the real corpus for every single retrieval case would be wasteful
    and is unnecessary: the corpus and the deterministic embedding
    provider are both fixed for the lifetime of one evaluation run."""
    cache_key = str(_knowledge_root())
    if cache_key in _INDEX_CACHE:
        return _INDEX_CACHE[cache_key]

    docs = load_knowledge_documents(str(_knowledge_root()))
    if not docs:
        raise FileNotFoundError(f"real knowledge/runbooks corpus not found at {_knowledge_root()}")

    provider = LocalLexicalEmbeddingProvider()
    chunks: list[tuple[str, list[float]]] = []
    for doc in docs:
        pieces = chunk_text(doc.text, max_chars=1200, overlap_chars=150)
        embeddings = await provider.embed(pieces)
        for _text, embedding in zip(pieces, embeddings, strict=True):
            chunks.append((doc.source_key, embedding))
    _INDEX_CACHE[cache_key] = chunks
    return chunks


async def score_retrieval_case(case: Case) -> CaseResult:
    try:
        query = case.input["query"]
        relevant_source_keys = set(case.input.get("relevant_source_keys", []))
        top_k = int(case.expected_outcome["top_k"])
        require_hit = bool(case.expected_outcome["require_hit"])
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=f"malformed retrieval case input/expected_outcome: {exc}",
        )

    try:
        chunks = await _indexed_chunks()
    except FileNotFoundError as exc:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.NOT_EVALUATED,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=str(exc),
        )

    provider = LocalLexicalEmbeddingProvider()
    [query_vec] = await provider.embed([query])
    ranked = sorted(chunks, key=lambda c: -_cosine(c[1], query_vec))

    # Rank by FIRST occurrence of each distinct source_key (a document
    # is chunked into several pieces; what matters for this metric is
    # whether the document itself surfaces, not a specific chunk).
    seen: set[str] = set()
    ranked_sources: list[str] = []
    for source_key, _vec in ranked:
        if source_key not in seen:
            seen.add(source_key)
            ranked_sources.append(source_key)

    top_k_sources = ranked_sources[:top_k]
    hit = any(key in relevant_source_keys for key in top_k_sources)

    reciprocal_rank = 0.0
    for rank, source_key in enumerate(ranked_sources, start=1):
        if source_key in relevant_source_keys:
            reciprocal_rank = 1.0 / rank
            break

    metrics = {"hit_at_k": 1.0 if hit else 0.0, "reciprocal_rank": reciprocal_rank}

    if hit != require_hit:
        return CaseResult(
            case_id=case.case_id,
            category=case.category,
            evaluation_mode=case.evaluation_mode,
            result=Result.FAIL,
            is_hard_safety_invariant=case.is_hard_safety_invariant,
            detail=(
                f"query {query!r}: expected require_hit={require_hit} for relevant_source_keys="
                f"{sorted(relevant_source_keys)}, got hit={hit} (top-{top_k}: {top_k_sources})"
            ),
            metrics=metrics,
        )
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        evaluation_mode=case.evaluation_mode,
        result=Result.PASS,
        is_hard_safety_invariant=case.is_hard_safety_invariant,
        detail=f"query {query!r}: hit={hit} matched require_hit={require_hit} (top-{top_k}: {top_k_sources})",
        metrics=metrics,
    )
