"""Gate B + Gate H tests: deterministic parsing, schema integrity, and
validation -- including the negative controls Gate H requires. Uses
synthetic fixtures for negative tests; never touches a real incident,
database, or remediation path."""

import pathlib

import pytest

from catalog.importer.build import build_catalog, load_built_catalog, write_catalog
from catalog.importer.parser import ParseError, parse_source
from catalog.validation.validate import (
    EXPECTED_DOMAIN_COUNT,
    EXPECTED_SCENARIOS_PER_DOMAIN,
    EXPECTED_TOTAL_SCENARIOS,
    validate_catalog,
)

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_VALID_MINIMAL = (_FIXTURES / "valid_minimal.md").read_text()


def _parse(text: str):
    return parse_source(text, "fixtures/valid_minimal.md", "v1")


# ---------------------------------------------------------------------
# Positive: the real, full source file
# ---------------------------------------------------------------------


def test_real_catalog_builds_all_800_scenarios_without_loss():
    manifest = build_catalog()
    assert len(manifest.scenarios) == EXPECTED_TOTAL_SCENARIOS


def test_real_catalog_has_exactly_40_domains_with_20_each():
    manifest = build_catalog()
    by_domain: dict[str, int] = {}
    for s in manifest.scenarios:
        by_domain[s.domain_id] = by_domain.get(s.domain_id, 0) + 1
    assert len(by_domain) == EXPECTED_DOMAIN_COUNT
    assert all(count == EXPECTED_SCENARIOS_PER_DOMAIN for count in by_domain.values())


def test_real_catalog_has_no_duplicate_ids():
    manifest = build_catalog()
    ids = [s.scenario_id for s in manifest.scenarios]
    assert len(ids) == len(set(ids))


def test_real_catalog_passes_validation_cleanly():
    manifest = build_catalog()
    report = validate_catalog(manifest)
    assert report.ok, report.violations


def test_real_catalog_build_is_deterministic_across_runs(tmp_path):
    manifest_a = build_catalog()
    manifest_b = build_catalog()
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    write_catalog(manifest_a, out_a)
    write_catalog(manifest_b, out_b)
    assert out_a.read_text() == out_b.read_text()


def test_real_catalog_fields_are_traceable_to_source_lines():
    manifest = build_catalog()
    source_text = pathlib.Path(manifest.source_file).read_text() if pathlib.Path(manifest.source_file).is_file() else None
    sample = next(s for s in manifest.scenarios if s.scenario_id == "D01-F01")
    assert sample.source_provenance.source_file == manifest.source_file
    assert sample.source_provenance.block_start_line < sample.source_provenance.block_end_line
    assert sample.source_provenance.source_sha256 == manifest.source_sha256


def test_load_built_catalog_round_trips(tmp_path):
    manifest = build_catalog()
    out = tmp_path / "catalog.json"
    write_catalog(manifest, out)
    reloaded = load_built_catalog(out)
    assert reloaded == manifest


# ---------------------------------------------------------------------
# Positive: the tiny synthetic fixture (fast, isolated parser checks)
# ---------------------------------------------------------------------


def test_minimal_fixture_parses_all_four_scenarios():
    _, _, scenarios = _parse(_VALID_MINIMAL)
    assert [s.scenario_id for s in scenarios] == ["D01-F01", "D01-F02", "D02-F01", "D02-F02"]


def test_minimal_fixture_fails_validation_on_wrong_counts():
    """A structurally well-formed but incomplete catalog (not 40x20)
    must fail validation loudly, never silently pass as 'close enough'."""
    preamble, closing, scenarios = _parse(_VALID_MINIMAL)
    from catalog.schemas.catalog import CatalogManifest

    manifest = CatalogManifest(
        catalog_version="v1",
        source_file="fixtures/valid_minimal.md",
        source_sha256="0" * 64,
        generated_at="deterministic-build",
        scenario_count=len(scenarios),
        domain_count=len({s.domain_id for s in scenarios}),
        preamble=preamble,
        closing=closing,
        scenarios=scenarios,
    )
    report = validate_catalog(manifest)
    assert not report.ok
    assert any("expected exactly 40 domains" in v for v in report.violations)
    assert any("expected exactly 20 scenarios" in v for v in report.violations)


# ---------------------------------------------------------------------
# Negative controls (Gate H) -- synthetic corruption, never real data
# ---------------------------------------------------------------------


def test_missing_bullet_fails_parsing_clearly():
    corrupted = _VALID_MINIMAL.replace(
        "- **Likely causes:** causes text one.\n", "", 1
    )
    with pytest.raises(ParseError, match="likely_causes"):
        _parse(corrupted)


def test_malformed_class_line_fails_parsing_clearly():
    corrupted = _VALID_MINIMAL.replace(
        "**Class:** Test class · **Default severity:** Critical · **Automation:** Investigate / propose fix",
        "**Class:** Test class -- Default severity Critical -- Automation broken",
        1,
    )
    with pytest.raises(ParseError, match="Class/Severity/Automation"):
        _parse(corrupted)


def test_malformed_scenario_heading_fails_parsing_clearly():
    corrupted = _VALID_MINIMAL.replace(
        "### D01-F01 — First scenario", "### D01F01 First scenario", 1
    )
    with pytest.raises(ParseError, match="malformed scenario heading"):
        _parse(corrupted)


def test_duplicate_scenario_id_parses_but_fails_validation():
    """Two blocks sharing one ID must parse (the parser does not
    de-duplicate or guess) but must be caught, loudly, by validation."""
    corrupted = _VALID_MINIMAL.replace("D01-F02", "D01-F01")
    preamble, closing, scenarios = _parse(corrupted)
    from catalog.schemas.catalog import CatalogManifest

    manifest = CatalogManifest(
        catalog_version="v1",
        source_file="fixtures/valid_minimal.md",
        source_sha256="0" * 64,
        generated_at="deterministic-build",
        scenario_count=len(scenarios),
        domain_count=len({s.domain_id for s in scenarios}),
        preamble=preamble,
        closing=closing,
        scenarios=scenarios,
    )
    report = validate_catalog(manifest)
    assert not report.ok
    assert any("duplicate scenario_id" in v for v in report.violations)


def test_out_of_range_scenario_id_parses_but_fails_validation():
    """D41 is syntactically well-formed (matches D\\d{2}) but is
    outside the real 1..40 domain range -- must fail at validation,
    never silently accepted as a 41st domain."""
    corrupted = _VALID_MINIMAL.replace("D02-F01", "D41-F01").replace("D02-F02", "D41-F02")
    preamble, closing, scenarios = _parse(corrupted)
    from catalog.schemas.catalog import CatalogManifest

    manifest = CatalogManifest(
        catalog_version="v1",
        source_file="fixtures/valid_minimal.md",
        source_sha256="0" * 64,
        generated_at="deterministic-build",
        scenario_count=len(scenarios),
        domain_count=len({s.domain_id for s in scenarios}),
        preamble=preamble,
        closing=closing,
        scenarios=scenarios,
    )
    report = validate_catalog(manifest)
    assert not report.ok
    assert any("outside 1..40" in v for v in report.violations)


def test_unexpected_empty_heading_fails_parsing_clearly():
    """An extra, unrecognized '## ' heading with no scenarios under it
    must never vanish with no trace -- it is a hard `ParseError`."""
    corrupted = _VALID_MINIMAL.replace(
        "## Implementation guidance",
        "## An Unexpected Injected Heading\n\n## Implementation guidance",
        1,
    )
    with pytest.raises(ParseError, match="unexpected heading"):
        _parse(corrupted)




def test_missing_required_field_value_fails_validation():
    """A bullet line present with a whitespace-only value parses (the
    regex is satisfied by any single character, including a space) but
    must still fail validation's required-field check once stripped."""
    corrupted = _VALID_MINIMAL.replace(
        "- **Detection:** detection text one.", "- **Detection:**  ", 1
    )
    preamble, closing, scenarios = _parse(corrupted)
    from catalog.schemas.catalog import CatalogManifest

    manifest = CatalogManifest(
        catalog_version="v1",
        source_file="fixtures/valid_minimal.md",
        source_sha256="0" * 64,
        generated_at="deterministic-build",
        scenario_count=len(scenarios),
        domain_count=len({s.domain_id for s in scenarios}),
        preamble=preamble,
        closing=closing,
        scenarios=scenarios,
    )
    report = validate_catalog(manifest)
    assert not report.ok
    assert any("detection_description" in v and "missing or blank" in v for v in report.violations)


def test_corrupted_source_file_makes_build_catalog_raise(tmp_path):
    """Simulates the CLI's own contract end to end: an intentionally
    corrupted source FILE (not just in-memory text) must cause
    `build_catalog` itself to raise `BuildError` (which the CLI turns
    into a nonzero exit code), never silently produce a partial
    catalog."""
    from catalog.importer.build import BuildError, build_catalog as _build_catalog

    corrupted = _VALID_MINIMAL.replace(
        "**Class:** Test class · **Default severity:** Critical · **Automation:** Investigate / propose fix",
        "totally broken line",
        1,
    )
    corrupted_path = tmp_path / "corrupted.md"
    corrupted_path.write_text(corrupted)

    with pytest.raises(BuildError):
        _build_catalog(source_path=corrupted_path)


def test_orphan_line_between_scenario_blocks_fails_parsing_clearly():
    """Correction-round Issue 3: a nonblank line inserted between two
    otherwise-valid scenario blocks must never be silently accepted."""
    corrupted = _VALID_MINIMAL.replace(
        "### D01-F02",
        "THIS IS AN UNEXPECTED ORPHAN LINE THAT SHOULD NOT BE ACCEPTED\n\n### D01-F02",
        1,
    )
    with pytest.raises(ParseError, match="unexpected content outside any recognized document section"):
        _parse(corrupted)


def test_orphan_line_still_raises_even_though_scenario_count_stays_800_on_real_source():
    """The same check, reproduced against a copy of the REAL source
    (not just the tiny fixture) -- confirms the fix holds at scale,
    not only on the minimal synthetic case."""
    import pathlib as _pathlib

    real_text = (_pathlib.Path(__file__).parent.parent / "source" / "40-domains-800-scenarios.md").read_text()
    lines = real_text.split("\n")
    insertion_idx = next(i for i, l in enumerate(lines) if l.startswith("### D01-F02"))
    lines.insert(insertion_idx, "THIS IS AN UNEXPECTED ORPHAN LINE THAT SHOULD NOT BE ACCEPTED")
    corrupted_real = "\n".join(lines)
    with pytest.raises(ParseError, match="unexpected content outside any recognized document section"):
        parse_source(corrupted_real, "catalog/source/40-domains-800-scenarios.md", "v1")


def test_trailing_content_after_closing_guidance_fails_parsing_clearly():
    """Correction-round Issue 3: content appended AFTER the closing
    'Implementation guidance' section must never be silently dropped."""
    corrupted = _VALID_MINIMAL + "\nUNEXPECTED TRAILING CONTENT AFTER CLOSING GUIDANCE\n"
    with pytest.raises(ParseError, match="unexpected content outside any recognized document section"):
        _parse(corrupted)


def test_legitimate_blank_line_formatting_is_still_accepted():
    """Guards against over-correcting: ordinary blank-line spacing
    between blocks (the real source's own style) must never be
    flagged as an orphan."""
    _, _, scenarios = _parse(_VALID_MINIMAL)
    assert len(scenarios) == 4


def test_intentionally_missing_scenario_is_detected_as_domain_count_mismatch():
    """Deleting an entire scenario block (not just a field) must be
    caught as a per-domain count mismatch, never silently accepted as
    a smaller-but-fine domain."""
    corrupted = _VALID_MINIMAL.split("### D02-F02")[0]  # drop the last block and closing section
    corrupted += "\n## Implementation guidance\n\n1. placeholder.\n"
    preamble, closing, scenarios = _parse(corrupted)
    assert "D02-F02" not in [s.scenario_id for s in scenarios]
    from catalog.schemas.catalog import CatalogManifest

    manifest = CatalogManifest(
        catalog_version="v1",
        source_file="fixtures/valid_minimal.md",
        source_sha256="0" * 64,
        generated_at="deterministic-build",
        scenario_count=len(scenarios),
        domain_count=len({s.domain_id for s in scenarios}),
        preamble=preamble,
        closing=closing,
        scenarios=scenarios,
    )
    report = validate_catalog(manifest)
    assert not report.ok
    assert any("domain 'D02'" in v and "expected exactly 20" in v for v in report.violations)
