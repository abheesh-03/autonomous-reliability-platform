"""Tests for redaction.py — Phase 5 correction round #7: "Apply
reasonable bounded redaction to known credential patterns before
model submission." Deliberately NOT a claim of completeness (see the
module's own docstring and the final "limitation" test below)."""

from investigator_service.redaction import redact


def test_redacts_bearer_token():
    text = redact("received request with Authorization: Bearer sk-realtoken1234567890")
    assert "sk-realtoken1234567890" not in text
    assert "REDACTED" in text


def test_redacts_authorization_header():
    text = redact("Authorization: Basic dXNlcjpwYXNz")
    assert "dXNlcjpwYXNz" not in text
    assert "REDACTED" in text


def test_redacts_inline_api_key_assignment():
    text = redact("config loaded api_key=sk-abcdefghijklmnopqrstuvwxyz request failed")
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in text
    assert "REDACTED" in text


def test_redacts_inline_password_assignment():
    text = redact("db connection password=SuperSecret123! refused")
    assert "SuperSecret123!" not in text
    assert "REDACTED" in text


def test_redacts_aws_access_key_id():
    text = redact("found credential AKIAIOSFODNN7EXAMPLE in log")
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert "REDACTED_AWS_KEY_ID" in text


def test_redacts_openai_style_secret_key():
    text = redact("using key sk-proj-abcdefghijklmnopqrstuvwxyz1234567890")
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890" not in text
    assert "REDACTED_API_KEY" in text


def test_leaves_ordinary_text_unchanged():
    text = "checkout-service returned HTTP 502 for payment-service"
    assert redact(text) == text


def test_redaction_is_best_effort_not_a_completeness_guarantee():
    """Stated honestly: an unusual or obfuscated secret shape is not
    guaranteed to match any pattern here. This test documents that
    limitation directly rather than asserting a false guarantee."""
    obfuscated = "s3cr3t_v4lu3=Zm9vYmFyYmF6cXV1eA=="  # not a recognized pattern
    assert redact(obfuscated) == obfuscated  # passes through unredacted, by design limitation
