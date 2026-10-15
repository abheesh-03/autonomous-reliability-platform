"""Tests for text_safety.py.

Phase 7 correction round, finding #4: independent review reproduced
`title = "x" * 5000` persisted at length 5000, and
`description = "Bearer TOPSECRET"` persisted unchanged.

Phase 7 correction round follow-up:
- finding #1: independent review reproduced `max_text_chars=2000`
  actually persisting a 2014-character string (the truncation suffix
  was appended AFTER slicing to the configured maximum, instead of
  reserving space for it). These tests assert the REAL hard-bound
  invariant: `len(value) <= configured_max`, never
  `configured_max + len(suffix)`.
- finding #2: independent review reproduced
  `source_fingerprint = "Bearer TOPSECRET" + 5000 chars` persisted at
  full length, completely unredacted. `source`/`source_fingerprint`
  are now bounded/redacted exactly like `title`/`description`.

test_graph.py's own tests prove this is actually wired into
load_incident's real output; these tests prove the helper itself.
"""

from agent_runtime_service.text_safety import bound_and_redact, hard_bound

MAX_CHARS = 2000


def _clean_snapshot(**overrides) -> dict:
    base = {
        "title": "checkout-service is returning HTTP 5xx errors",
        "description": "normal description",
        "source": "alertmanager",
        "source_fingerprint": "deadbeef12345678",
    }
    base.update(overrides)
    return base


# --- hard_bound: the real, reusable truncation primitive ---------------


def test_hard_bound_never_exceeds_max_chars_including_suffix():
    result = hard_bound("x" * 5000, MAX_CHARS)
    assert len(result) <= MAX_CHARS
    assert result.endswith("...[truncated]")


def test_hard_bound_leaves_short_text_unchanged():
    assert hard_bound("short", MAX_CHARS) == "short"


def test_hard_bound_defensive_when_max_chars_smaller_than_suffix():
    # Never true for this service's own clamped config in practice, but
    # must never produce something LONGER than max_chars regardless.
    result = hard_bound("x" * 100, 5)
    assert len(result) <= 5


# --- oversized fields are hard-bounded, not just "bounded-plus-suffix" --


def test_oversized_title_is_hard_bounded():
    snapshot = _clean_snapshot(title="x" * 5000)
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert len(result["title"]) <= MAX_CHARS
    assert result["title"].endswith("...[truncated]")
    assert "x" * 5000 != result["title"]


def test_oversized_description_is_hard_bounded():
    snapshot = _clean_snapshot(description="y" * 5000)
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert len(result["description"]) <= MAX_CHARS
    assert "y" * 5000 != result["description"]


def test_oversized_source_is_hard_bounded():
    snapshot = _clean_snapshot(source="z" * 5000)
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert len(result["source"]) <= MAX_CHARS
    assert "z" * 5000 != result["source"]


def test_oversized_source_fingerprint_is_hard_bounded():
    """Independent review's exact reproduction case."""
    snapshot = _clean_snapshot(source_fingerprint="Bearer TOPSECRET" + ("w" * 5000))
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert len(result["source_fingerprint"]) <= MAX_CHARS


# --- redaction: all four free-text fields ------------------------------


def test_bearer_token_in_description_is_redacted():
    snapshot = _clean_snapshot(description="auth failed: Bearer sk-TOPSECRET123456789012345")
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert "TOPSECRET" not in result["description"]
    assert "Bearer [REDACTED]" in result["description"]


def test_api_key_assignment_in_title_is_redacted():
    snapshot = _clean_snapshot(title="api_key=sk-should-never-appear-anywhere-1234567890")
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert "sk-should-never-appear" not in result["title"]


def test_bearer_token_shaped_source_fingerprint_is_redacted():
    """Independent review's exact reproduction case: a credential-shaped
    fingerprint value must be redacted, not merely bounded."""
    snapshot = _clean_snapshot(source_fingerprint="Bearer sk-TOPSECRET1234567890123456789")
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert "TOPSECRET" not in result["source_fingerprint"]
    assert "Bearer [REDACTED]" in result["source_fingerprint"]


def test_secret_shaped_source_is_redacted():
    snapshot = _clean_snapshot(source="token=sk-should-not-leak-in-source-field-123456")
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert "sk-should-not-leak-in-source-field" not in result["source"]


# --- clean values and non-text fields pass through unchanged -----------


def test_none_description_passes_through_unchanged():
    snapshot = _clean_snapshot(description=None)
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert result["description"] is None


def test_clean_normal_alertmanager_values_remain_unchanged():
    snapshot = _clean_snapshot()
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert result["title"] == snapshot["title"]
    assert result["description"] == snapshot["description"]
    assert result["source"] == snapshot["source"]
    assert result["source_fingerprint"] == snapshot["source_fingerprint"]


def test_does_not_mutate_the_input_dict():
    snapshot = _clean_snapshot(title="Bearer sk-leak-me-1234567890123456789012")
    original = dict(snapshot)
    bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert snapshot == original


def test_non_bounded_fields_pass_through_unchanged():
    """UUIDs, enums, and timestamps are never touched -- only the four
    known free-text fields are bounded/redacted."""
    snapshot = _clean_snapshot(
        **{
            "id": "33333333-3333-3333-3333-333333333333",
            "status": "open",
            "severity": "critical",
            "first_seen_at": "2026-04-01T09:00:00+00:00",
        }
    )
    result = bound_and_redact(snapshot, max_text_chars=MAX_CHARS)
    assert result["id"] == snapshot["id"]
    assert result["status"] == snapshot["status"]
    assert result["severity"] == snapshot["severity"]
    assert result["first_seen_at"] == snapshot["first_seen_at"]
