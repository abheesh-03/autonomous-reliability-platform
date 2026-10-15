"""Tests for config.py -- bounds are clamped to a sane range, never
able to silently disable a real bound, matching the exact convention
investigator_service.config already establishes."""

import os

import pytest

from retrieval_service.config import EMBEDDING_DIMENSION, IndexingBounds, SearchBounds


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("RETRIEVAL_"):
            monkeypatch.delenv(key, raising=False)


def test_embedding_dimension_is_fixed_at_1536():
    assert EMBEDDING_DIMENSION == 1536


def test_indexing_bounds_defaults():
    bounds = IndexingBounds.from_env()
    assert bounds.knowledge_root == "/knowledge"
    assert bounds.max_chunk_chars == 1200


def test_indexing_bounds_clamp_out_of_range_values(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MAX_CHUNK_CHARS", "999999999")
    monkeypatch.setenv("RETRIEVAL_CHUNK_OVERLAP_CHARS", "-5")
    bounds = IndexingBounds.from_env()
    assert bounds.max_chunk_chars == 8000  # clamped to the maximum
    assert bounds.chunk_overlap_chars == 0  # clamped to the minimum


def test_search_bounds_clamp_out_of_range_values(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MAX_RESULT_LIMIT", "0")
    monkeypatch.setenv("RETRIEVAL_MAX_QUERY_LENGTH", "999999999")
    bounds = SearchBounds.from_env()
    assert bounds.max_result_limit == 1  # clamped to the minimum
    assert bounds.max_query_length == 10_000  # clamped to the maximum


def test_search_bounds_defaults_are_sane():
    bounds = SearchBounds.from_env()
    assert bounds.default_result_limit <= bounds.max_result_limit
