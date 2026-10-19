"""Correction-round Issue 4: a catalog that parses but fails Gate B's
own structural validation (e.g. one missing scenario block -> 799
instead of 800 scenarios) must never be written out by the CLI as if
it were a successful build/audit/coverage run. `build_catalog` alone
stays validation-free on purpose (so focused unit tests can still
construct an intentionally incomplete manifest directly, as several
existing Gate B tests already do); `build_and_validate_catalog` and
every CLI subcommand that writes an artifact must fail closed instead.
"""

import hashlib
import pathlib
import subprocess
import sys

import pytest

from catalog.importer.build import BuildError, DEFAULT_SOURCE_PATH, build_and_validate_catalog, build_catalog

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _real_source_missing_one_scenario_block(tmp_path: pathlib.Path) -> pathlib.Path:
    """A copy of the REAL 800-scenario source with exactly one
    complete scenario block (D01-F02, 10 lines) deleted -- otherwise
    byte-identical, so this reproduces the independent reviewer's own
    'removed one complete, otherwise well-formed scenario block' case
    against the real file, not just a tiny synthetic fixture."""
    lines = DEFAULT_SOURCE_PATH.read_text().split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("### D01-F02"))
    # The fixed 10-line block shape (heading, blank, class line, blank,
    # 6 bullets) -- see catalog/importer/parser.py's own module
    # docstring for why this shape is exact and unvarying.
    del lines[start : start + 10]
    corrupted_path = tmp_path / "missing-one-scenario.md"
    corrupted_path.write_text("\n".join(lines))
    return corrupted_path


def test_build_catalog_alone_still_returns_the_incomplete_manifest(tmp_path):
    """Preserves the documented escape hatch: a focused unit test can
    still construct an intentionally incomplete manifest via plain
    `build_catalog` (no validation gate) for its own assertions."""
    corrupted = _real_source_missing_one_scenario_block(tmp_path)
    manifest = build_catalog(source_path=corrupted)
    assert len(manifest.scenarios) == 799
    assert "D01-F02" not in {s.scenario_id for s in manifest.scenarios}


def test_build_and_validate_catalog_raises_on_incomplete_source(tmp_path):
    corrupted = _real_source_missing_one_scenario_block(tmp_path)
    with pytest.raises(BuildError, match="failed structural validation"):
        build_and_validate_catalog(source_path=corrupted)


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "catalog", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_build_exits_nonzero_and_writes_nothing_on_incomplete_source(tmp_path):
    corrupted = _real_source_missing_one_scenario_block(tmp_path)
    output_path = tmp_path / "catalog-output.json"
    result = _run_cli(["build", "--source", str(corrupted), "--output", str(output_path)])
    assert result.returncode != 0, result.stdout + result.stderr
    assert "failed structural validation" in (result.stdout + result.stderr)
    assert not output_path.exists(), "an incomplete catalog must never be written as a successful build artifact"


def test_cli_build_does_not_overwrite_an_existing_output_on_incomplete_source(tmp_path):
    """Output preservation: a pre-existing artifact at the destination
    path must be byte-identical before and after a failed build."""
    corrupted = _real_source_missing_one_scenario_block(tmp_path)
    output_path = tmp_path / "catalog-output.json"
    original_content = '{"previously": "written", "by": "a successful build"}'
    output_path.write_text(original_content)
    original_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()

    result = _run_cli(["build", "--source", str(corrupted), "--output", str(output_path)])

    assert result.returncode != 0
    assert output_path.read_text() == original_content
    assert hashlib.sha256(output_path.read_bytes()).hexdigest() == original_hash


def test_cli_audit_exits_nonzero_and_writes_nothing_on_incomplete_source(tmp_path):
    corrupted = _real_source_missing_one_scenario_block(tmp_path)
    output_path = tmp_path / "audit-output.json"
    result = _run_cli(["audit", "--source", str(corrupted), "--output", str(output_path)])
    assert result.returncode != 0, result.stdout + result.stderr
    assert not output_path.exists()


def test_cli_coverage_exits_nonzero_and_writes_nothing_on_incomplete_source(tmp_path):
    corrupted = _real_source_missing_one_scenario_block(tmp_path)
    output_path = tmp_path / "coverage-output.json"
    result = _run_cli(["coverage", "--source", str(corrupted), "--output", str(output_path)])
    assert result.returncode != 0, result.stdout + result.stderr
    assert not output_path.exists()


def test_cli_validate_still_reports_itemized_violations_on_incomplete_source(tmp_path):
    """Non-regression: `validate` must keep its own, more detailed
    per-violation reporting -- it does not go through
    `build_and_validate_catalog`, it calls `validate_catalog` itself."""
    corrupted = _real_source_missing_one_scenario_block(tmp_path)
    result = _run_cli(["validate", "--source", str(corrupted)])
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "INVALID" in combined
    assert "domain 'D01'" in combined and "expected exactly 20" in combined


def test_cli_build_still_succeeds_and_writes_on_the_real_complete_source(tmp_path):
    """Non-regression: the real, complete 800-scenario source must
    still build and write successfully -- this correction must not
    make a genuinely valid catalog fail."""
    output_path = tmp_path / "catalog-output.json"
    result = _run_cli(["build", "--output", str(output_path)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert output_path.is_file()
