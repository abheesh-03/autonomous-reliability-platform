"""StubProvider tests — the deterministic, offline provider used by
every other test in this suite and by CI (Phase 5 §9/§6: "Use a
deterministic injected provider for CI. It must not require a real
paid API key.")."""

import json

from investigator_service.llm.provider import StubProvider


async def test_default_stub_response_is_valid_json_with_required_shape():
    provider = StubProvider()
    raw = await provider.investigate("system", "user")
    data = json.loads(raw)
    assert set(data) == {"summary", "observations", "hypotheses", "missing_evidence", "suggested_checks"}


async def test_default_stub_response_cites_e1_in_a_real_observation():
    """Phase 5 correction round #1: the default response must exercise
    the actual citation-validation path (E1 is always a real id — see
    evidence_collector.py's construction order), not pass trivially
    with every analysis section empty."""
    provider = StubProvider()
    data = json.loads(await provider.investigate("system", "user"))
    assert len(data["observations"]) >= 1
    assert any("E1" in obs["evidence_ids"] for obs in data["observations"])


async def test_stub_never_makes_a_network_call_and_is_deterministic():
    provider = StubProvider()
    first = await provider.investigate("system", "user")
    second = await provider.investigate("a totally different system prompt", "a totally different user prompt")
    assert first == second


async def test_stub_can_be_configured_with_custom_response_text():
    custom = '{"summary": "custom", "observations": [], "hypotheses": [], "missing_evidence": [], "suggested_checks": []}'
    provider = StubProvider(response_text=custom)
    raw = await provider.investigate("s", "u")
    assert raw == custom


def test_stub_provider_name_and_model_are_clearly_not_a_real_provider():
    provider = StubProvider()
    assert provider.name == "stub"
    assert "stub" in provider.model
