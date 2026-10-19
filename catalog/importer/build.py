"""Orchestrates parse -> normalize -> (optionally) validate -> write.
The single place `python -m catalog build`/`validate`/`audit`/
`coverage` all go through for parsing, so none of them can ever
silently diverge on how the catalog is actually constructed.

Correction-round Issue 4: `build_catalog` alone performs NO structural
validation (same as before -- `validate_catalog` is a separate,
reusable check, and `python -m catalog validate`'s own nicer,
itemized-violation reporting depends on being able to call it itself
rather than only ever seeing a pre-collapsed `BuildError` message).
What changed: every OTHER caller that writes an artifact --
`build`/`audit`/`coverage` in `catalog/cli/commands.py` -- now goes
through `build_and_validate_catalog` below instead of calling
`build_catalog` directly, so a catalog that parses but fails
structural validation (e.g. a missing scenario block) can never reach
a `write_catalog`/artifact-writing call. See
`catalog/tests/test_build_validation_gate.py` for the exact negative
control (a 799-scenario synthetic source must make `build` itself
fail, not just `validate`)."""

import pathlib

from catalog.importer.parser import ParseError, parse_source
from catalog.schemas.catalog import CatalogManifest
from catalog.validation.validate import validate_catalog

CATALOG_VERSION = "v1"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_PATH = _REPO_ROOT / "catalog" / "source" / "40-domains-800-scenarios.md"
DEFAULT_BUILD_OUTPUT = _REPO_ROOT / "catalog" / "build" / "catalog.v1.json"
SOURCE_RELATIVE_PATH = "catalog/source/40-domains-800-scenarios.md"


class BuildError(Exception):
    pass


def build_catalog(source_path: pathlib.Path = DEFAULT_SOURCE_PATH, catalog_version: str = CATALOG_VERSION) -> CatalogManifest:
    if not source_path.is_file():
        raise BuildError(f"source catalog not found: {source_path}")
    text = source_path.read_text(encoding="utf-8")

    try:
        preamble, closing, scenarios = parse_source(text, SOURCE_RELATIVE_PATH, catalog_version)
    except ParseError as exc:
        raise BuildError(f"source catalog failed to parse: {exc}") from exc

    from catalog.importer.parser import sha256_of

    return CatalogManifest(
        catalog_version=catalog_version,
        source_file=SOURCE_RELATIVE_PATH,
        source_sha256=sha256_of(text),
        generated_at="deterministic-build",  # never a wall-clock timestamp -- see write_catalog()'s own docstring
        scenario_count=len(scenarios),
        domain_count=len({s.domain_id for s in scenarios}),
        preamble=preamble,
        closing=closing,
        scenarios=scenarios,
    )


def build_and_validate_catalog(
    source_path: pathlib.Path = DEFAULT_SOURCE_PATH, catalog_version: str = CATALOG_VERSION
) -> CatalogManifest:
    """`build_catalog`, then a MANDATORY structural-validation gate --
    raises `BuildError` (never returns, never lets a caller write an
    artifact) if the catalog parses but fails `validate_catalog`. Every
    CLI subcommand that WRITES an artifact (`build`, `audit`,
    `coverage`) must call this, not `build_catalog` directly, so an
    incomplete or malformed catalog (e.g. a missing scenario block)
    can never be written out as if it were a successful build."""
    manifest = build_catalog(source_path=source_path, catalog_version=catalog_version)
    report = validate_catalog(manifest)
    if not report.ok:
        violations = "; ".join(report.violations)
        raise BuildError(f"source catalog parsed but failed structural validation: {violations}")
    return manifest


def write_catalog(manifest: CatalogManifest, output_path: pathlib.Path = DEFAULT_BUILD_OUTPUT) -> None:
    """Writes the normalized catalog as canonical, deterministic JSON
    -- Gate B's own 'deterministic stable output' requirement.
    `generated_at` is deliberately a FIXED sentinel, never
    `datetime.now()`: a build artifact's byte-for-byte reproducibility
    (confirmed by `tests/test_parser.py::test_build_is_byte_identical_
    across_runs`) would otherwise be defeated by its own timestamp on
    every single run, which would make `git diff` on this
    version-controlled artifact meaningless for reviewing an ACTUAL
    source change."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(manifest.model_dump_json(indent=2) + "\n")


def load_built_catalog(path: pathlib.Path = DEFAULT_BUILD_OUTPUT) -> CatalogManifest:
    if not path.is_file():
        raise BuildError(f"no built catalog found at {path} -- run 'python -m catalog build' first")
    return CatalogManifest.model_validate_json(path.read_text())
