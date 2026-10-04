"""LLMSettings provider-selection tests — in particular that `stub`
mode (used only by scripts/verify-investigator.sh) reports itself as
configured without any API key, while the default `openai` mode
honestly requires one.

Also covers the Phase 5 correction round's "validate configuration
bounds so environment variables cannot accidentally disable practical
limits" requirement for EvidenceBounds."""

from investigator_service.config import EvidenceBounds, LLMSettings


def test_openai_mode_unconfigured_without_api_key(monkeypatch):
    monkeypatch.delenv("INVESTIGATOR_LLM_API_KEY", raising=False)
    monkeypatch.delenv("INVESTIGATOR_LLM_PROVIDER", raising=False)
    settings = LLMSettings.from_env()
    assert settings.provider == "openai"
    assert settings.configured is False


def test_openai_mode_configured_with_api_key(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_LLM_API_KEY", "sk-test")
    monkeypatch.delenv("INVESTIGATOR_LLM_PROVIDER", raising=False)
    settings = LLMSettings.from_env()
    assert settings.configured is True


def test_stub_mode_is_always_configured_without_any_key(monkeypatch):
    monkeypatch.delenv("INVESTIGATOR_LLM_API_KEY", raising=False)
    monkeypatch.setenv("INVESTIGATOR_LLM_PROVIDER", "stub")
    settings = LLMSettings.from_env()
    assert settings.provider == "stub"
    assert settings.configured is True


def test_invalid_provider_value_falls_back_to_openai(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_LLM_PROVIDER", "something-bogus")
    monkeypatch.delenv("INVESTIGATOR_LLM_API_KEY", raising=False)
    settings = LLMSettings.from_env()
    assert settings.provider == "openai"


def test_evidence_bounds_clamp_a_value_below_the_minimum(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_MAX_LOKI_LINES", "0")
    bounds = EvidenceBounds.from_env()
    assert bounds.max_loki_lines == 1  # the documented minimum, never 0


def test_evidence_bounds_clamp_a_value_above_the_maximum(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_MAX_LOKI_LINES", "999999999")
    bounds = EvidenceBounds.from_env()
    assert bounds.max_loki_lines == 500  # the documented maximum


def test_evidence_bounds_clamp_negative_audit_events(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_MAX_AUDIT_EVENTS", "-5")
    bounds = EvidenceBounds.from_env()
    assert bounds.max_audit_events == 1


def test_evidence_bounds_clamp_prompt_chars_ceiling(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_MAX_PROMPT_CHARS", "0")
    bounds = EvidenceBounds.from_env()
    assert bounds.max_prompt_chars == 2_000  # never disablable down to 0


def test_evidence_bounds_clamp_prompt_evidence_items(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_MAX_PROMPT_EVIDENCE_ITEMS", "1000000")
    bounds = EvidenceBounds.from_env()
    assert bounds.max_prompt_evidence_items == 500


def test_evidence_bounds_in_range_value_passes_through_unchanged(monkeypatch):
    monkeypatch.setenv("INVESTIGATOR_MAX_LOKI_LINES", "42")
    bounds = EvidenceBounds.from_env()
    assert bounds.max_loki_lines == 42


def test_evidence_bounds_defaults_are_within_their_own_clamp_ranges():
    """Sanity check: the documented defaults must themselves survive
    clamping unchanged, or the defaults and the clamp ranges have
    drifted out of sync."""
    bounds = EvidenceBounds.from_env()
    assert bounds.max_audit_events == 200
    assert bounds.max_prometheus_series == 10
    assert bounds.max_loki_lines == 20
    assert bounds.max_loki_line_length == 500
    assert bounds.max_tempo_traces == 5
    assert bounds.max_incident_text_length == 2000
    assert bounds.max_prompt_evidence_items == 80
    assert bounds.max_prompt_chars == 40_000
