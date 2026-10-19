"""Gate B validation: every hard integrity check the normalized
catalog must satisfy. Each check returns a list of violation strings
(empty = passes); the importer CLI (`python -m catalog validate`)
fails closed (nonzero exit) on ANY violation -- never a partial/
best-effort "mostly valid" result."""

import re

from catalog.schemas.catalog import CatalogManifest

_SCENARIO_ID_RE = re.compile(r"^D(\d{2})-F(\d{2})$")
EXPECTED_DOMAIN_COUNT = 40
EXPECTED_SCENARIOS_PER_DOMAIN = 20
EXPECTED_TOTAL_SCENARIOS = EXPECTED_DOMAIN_COUNT * EXPECTED_SCENARIOS_PER_DOMAIN

_REQUIRED_TEXT_FIELDS = (
    "title",
    "original_failure_class",
    "original_default_severity",
    "original_automation_label",
    "detection_description",
    "instrumentation_description",
    "likely_causes",
    "triage_description",
    "potential_remediation",
    "verification_description",
)


class ValidationReport:
    def __init__(self) -> None:
        self.violations: list[str] = []

    def fail(self, message: str) -> None:
        self.violations.append(message)

    @property
    def ok(self) -> bool:
        return not self.violations


def validate_catalog(manifest: CatalogManifest) -> ValidationReport:
    report = ValidationReport()
    scenarios = manifest.scenarios

    _validate_total_count(scenarios, report)
    _validate_domain_structure(scenarios, report)
    _validate_unique_ids(scenarios, report)
    _validate_id_structure(scenarios, report)
    _validate_required_fields(scenarios, report)
    _validate_manifest_counts(manifest, report)

    return report


def _validate_total_count(scenarios, report: ValidationReport) -> None:
    if len(scenarios) != EXPECTED_TOTAL_SCENARIOS:
        report.fail(f"expected exactly {EXPECTED_TOTAL_SCENARIOS} scenarios, got {len(scenarios)}")


def _validate_domain_structure(scenarios, report: ValidationReport) -> None:
    by_domain: dict[str, list[str]] = {}
    for s in scenarios:
        by_domain.setdefault(s.domain_id, []).append(s.scenario_id)

    if len(by_domain) != EXPECTED_DOMAIN_COUNT:
        report.fail(f"expected exactly {EXPECTED_DOMAIN_COUNT} domains, got {len(by_domain)}: {sorted(by_domain)}")

    for domain_id, ids in sorted(by_domain.items()):
        if len(ids) != EXPECTED_SCENARIOS_PER_DOMAIN:
            report.fail(
                f"domain {domain_id!r}: expected exactly {EXPECTED_SCENARIOS_PER_DOMAIN} scenarios, got {len(ids)}"
            )

    # Domain name consistency: a single domain_id must never map to two
    # different domain_name values (would mean a parsing/heading bug).
    domain_names: dict[str, set[str]] = {}
    for s in scenarios:
        domain_names.setdefault(s.domain_id, set()).add(s.domain_name)
    for domain_id, names in sorted(domain_names.items()):
        if len(names) > 1:
            report.fail(f"domain {domain_id!r} maps to multiple domain_name values: {sorted(names)}")


def _validate_unique_ids(scenarios, report: ValidationReport) -> None:
    seen: dict[str, int] = {}
    for s in scenarios:
        seen[s.scenario_id] = seen.get(s.scenario_id, 0) + 1
    duplicates = sorted(sid for sid, count in seen.items() if count > 1)
    if duplicates:
        report.fail(f"duplicate scenario_id(s) found: {duplicates}")


def _validate_id_structure(scenarios, report: ValidationReport) -> None:
    """Every id must match D01-F01 .. D40-F20 EXACTLY -- the real,
    expected domain/scenario numbering range, not merely the regex
    shape. A syntactically valid but out-of-range id (e.g. D41-F01 or
    D01-F21) is still a hard failure."""
    for s in scenarios:
        m = _SCENARIO_ID_RE.match(s.scenario_id)
        if not m:
            report.fail(f"malformed scenario_id: {s.scenario_id!r}")
            continue
        domain_num, scenario_num = int(m.group(1)), int(m.group(2))
        if not (1 <= domain_num <= EXPECTED_DOMAIN_COUNT):
            report.fail(f"{s.scenario_id!r}: domain number {domain_num} is outside 1..{EXPECTED_DOMAIN_COUNT}")
        if not (1 <= scenario_num <= EXPECTED_SCENARIOS_PER_DOMAIN):
            report.fail(
                f"{s.scenario_id!r}: scenario number {scenario_num} is outside 1..{EXPECTED_SCENARIOS_PER_DOMAIN}"
            )


def _validate_required_fields(scenarios, report: ValidationReport) -> None:
    for s in scenarios:
        for field_name in _REQUIRED_TEXT_FIELDS:
            value = getattr(s, field_name)
            if not isinstance(value, str) or not value.strip():
                report.fail(f"{s.scenario_id}: required field {field_name!r} is missing or blank")


def _validate_manifest_counts(manifest: CatalogManifest, report: ValidationReport) -> None:
    if manifest.scenario_count != len(manifest.scenarios):
        report.fail(
            f"manifest.scenario_count={manifest.scenario_count} does not match the real scenario list "
            f"length {len(manifest.scenarios)}"
        )
    actual_domains = len({s.domain_id for s in manifest.scenarios})
    if manifest.domain_count != actual_domains:
        report.fail(f"manifest.domain_count={manifest.domain_count} does not match the real domain count {actual_domains}")
