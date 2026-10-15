"""Tests for domain/search.py -- Phase 6 §9's request validation:
query length, result limits, UUID, no arbitrary extra fields."""

import uuid

import pytest
from pydantic import ValidationError

from retrieval_service.domain.search import SearchRequest


def test_valid_request_parses():
    req = SearchRequest(query="checkout errors", knowledge_limit=2, historical_incident_limit=2)
    assert req.query == "checkout errors"


def test_empty_query_is_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_query_over_max_length_is_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(query="x" * 10_001)


def test_negative_limit_is_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(query="x", knowledge_limit=-1)


def test_absurdly_large_limit_is_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(query="x", knowledge_limit=10_000)


def test_malformed_exclude_incident_id_is_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(query="x", exclude_incident_id="not-a-uuid")


def test_valid_exclude_incident_id_parses():
    uid = uuid.uuid4()
    req = SearchRequest(query="x", exclude_incident_id=str(uid))
    assert req.exclude_incident_id == uid


def test_unknown_extra_field_is_rejected():
    """Phase 6 §9: no arbitrary SQL/filter expression from the
    caller -- the request shape is a closed contract."""
    with pytest.raises(ValidationError):
        SearchRequest(query="x", sql="DROP TABLE reliability.retrieval_chunks")


def test_defaults_are_within_bounds():
    req = SearchRequest(query="x")
    assert req.knowledge_limit == 3
    assert req.historical_incident_limit == 3
    assert req.exclude_incident_id is None
