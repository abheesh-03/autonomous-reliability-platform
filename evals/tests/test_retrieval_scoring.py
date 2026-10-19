"""Exercises evals/scoring/retrieval.py against the real corpus, plus
Gate D negative controls."""

from evals.scoring.models import Result
from evals.scoring.retrieval import score_retrieval_case
from evals.tests.conftest import make_case


async def test_known_relevant_query_hits_its_real_runbook():
    case = make_case(
        evaluation_mode="retrieval",
        input={"query": "checkout 5xx payment dependency unavailable", "relevant_source_keys": ["runbooks/checkout-server-errors.md"]},
        expected_outcome={"top_k": 5, "require_hit": True},
    )
    result = await score_retrieval_case(case)
    assert result.result == Result.PASS
    assert result.metrics["hit_at_k"] == 1.0


async def test_negative_control_a_missed_required_runbook_is_reported_as_FAIL():
    """A case that (wrongly) expects a hit for a runbook the query is
    not about must FAIL -- proving the harness can detect a miss."""
    case = make_case(
        evaluation_mode="retrieval",
        input={"query": "checkout 5xx payment dependency unavailable", "relevant_source_keys": ["runbooks/collector-refusing-telemetry.md"]},
        expected_outcome={"top_k": 1, "require_hit": True},
    )
    result = await score_retrieval_case(case)
    assert result.result == Result.FAIL


async def test_irrelevant_runbook_correctly_scored_as_a_miss():
    case = make_case(
        evaluation_mode="retrieval",
        input={"query": "collector refusing telemetry", "relevant_source_keys": ["runbooks/checkout-high-latency.md"]},
        expected_outcome={"top_k": 2, "require_hit": False},
    )
    result = await score_retrieval_case(case)
    assert result.result == Result.PASS


async def test_malformed_case_input_is_not_evaluated():
    case = make_case(evaluation_mode="retrieval", input={}, expected_outcome={})
    result = await score_retrieval_case(case)
    assert result.result == Result.NOT_EVALUATED


async def test_missing_corpus_is_not_evaluated_never_a_silent_pass(monkeypatch):
    """Gate D: 'false success when a required measurement was
    skipped' -- pointing at a nonexistent knowledge root must NEVER
    look like a clean pass."""
    import evals.scoring.retrieval as retrieval_module

    monkeypatch.setenv(retrieval_module._KNOWLEDGE_ROOT_ENV, "/definitely/does/not/exist")
    retrieval_module._INDEX_CACHE.clear()
    case = make_case(
        evaluation_mode="retrieval",
        input={"query": "anything", "relevant_source_keys": []},
        expected_outcome={"top_k": 5, "require_hit": False},
    )
    result = await score_retrieval_case(case)
    assert result.result == Result.NOT_EVALUATED
    retrieval_module._INDEX_CACHE.clear()
