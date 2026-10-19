"""Gate B: deterministic source-to-structured-data parser.

Parses `catalog/source/40-domains-800-scenarios.md` by EXACT, fixed
line-position structure -- re-audited directly against the real file
before this module was written (every one of the 800 scenario blocks
was confirmed, programmatically, to match this exact 10-line shape
with zero anomalies; see the Gate A audit recorded in
`docs/architecture/phase-11a-incident-intelligence.md`). This is
intentionally a STRICT, position-based parser, never a fuzzy/
best-effort one: an unexpected heading, a missing bullet, or a
reordered field is a `ParseError`, never silently skipped or
guessed at. Never uses an LLM to fill in a missing or malformed
field -- Gate B's own explicit requirement.
"""

import hashlib
import re
from dataclasses import dataclass

from catalog.schemas.catalog import CatalogClosing, CatalogPreamble
from catalog.schemas.scenario import ScenarioRecord, SourceProvenance

_HEADING_RE = re.compile(r"^### (D\d{2}-F\d{2}) — (.+)$")
_DOMAIN_RE = re.compile(r"^## (.+)$")
_CLASS_RE = re.compile(r"^\*\*Class:\*\* (.+?) · \*\*Default severity:\*\* (\w+) · \*\*Automation:\*\* (.+)$")
_BULLET_RES: dict[str, re.Pattern] = {
    "detection_description": re.compile(r"^- \*\*Detection:\*\* (.+)$"),
    "instrumentation_description": re.compile(r"^- \*\*Evidence / instrumentation:\*\* (.+)$"),
    "likely_causes": re.compile(r"^- \*\*Likely causes:\*\* (.+)$"),
    "triage_description": re.compile(r"^- \*\*Triage:\*\* (.+)$"),
    "potential_remediation": re.compile(r"^- \*\*Potential remediation:\*\* (.+)$"),
    "verification_description": re.compile(r"^- \*\*Verification:\*\* (.+)$"),
}
_BULLET_ORDER = list(_BULLET_RES.keys())

# Section headings that are REAL, expected, non-domain "## " headings
# -- anything else encountered is an unexpected/malformed heading
# (Gate B's own explicit validation requirement), never silently
# ignored.
_NON_DOMAIN_SECTION_HEADINGS = frozenset({"Shared reliability foundation", "Implementation guidance"})


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class ParsedScenarioBlock:
    scenario_id: str
    domain_name: str
    title: str
    original_failure_class: str
    original_default_severity: str
    original_automation_label: str
    fields: dict[str, str]
    heading_line: int
    block_start_line: int
    block_end_line: int


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_blank(lines: list[str], idx: int, context: str) -> None:
    if idx >= len(lines) or lines[idx].strip() != "":
        raise ParseError(f"{context}: expected a blank line at line {idx + 1}, got {lines[idx] if idx < len(lines) else '<EOF>'!r}")


def parse_source(text: str, source_file: str, catalog_version: str) -> tuple[CatalogPreamble, CatalogClosing, list[ScenarioRecord]]:
    """Returns (preamble, closing, scenarios). Raises `ParseError` on
    ANY structural deviation from the exact expected format -- never a
    partial/best-effort result."""
    source_sha256 = sha256_of(text)
    lines = text.split("\n")

    preamble, preamble_end_idx = _parse_preamble(lines)
    domain_by_heading_line = _locate_domain_headings(lines)
    scenario_blocks = _parse_all_scenario_blocks(lines, domain_by_heading_line)
    closing, closing_start_idx, closing_end_idx = _parse_closing(lines)

    # A '## ' heading that is not one of the two known non-domain
    # sections but attaches zero scenario blocks is never silently
    # ignored (Gate B's 'no unexpected or malformed headings disappear
    # silently' requirement) -- every real domain in this source has
    # scenarios under it, so a heading with none is itself the anomaly.
    domains_with_scenarios = {block.domain_name for block in scenario_blocks}
    empty_headings = sorted(set(domain_by_heading_line.values()) - domains_with_scenarios)
    if empty_headings:
        raise ParseError(f"unexpected heading(s) with no scenarios attached: {empty_headings}")

    # Correction round Issue 3: every nonblank line must belong to a
    # recognized document region (preamble, a domain heading, a
    # scenario block, or the closing guidance section) -- an orphan
    # line inserted anywhere else (between two scenario blocks, or
    # trailing after the closing section) is never silently accepted.
    consumed_ranges = [(0, preamble_end_idx)]
    consumed_ranges += [(heading_idx, heading_idx) for heading_idx in domain_by_heading_line]
    consumed_ranges += [(block.heading_line - 1, block.block_end_line - 1) for block in scenario_blocks]
    consumed_ranges.append((closing_start_idx, closing_end_idx))
    _assert_no_orphan_lines(lines, consumed_ranges)

    scenarios = [
        ScenarioRecord(
            scenario_id=block.scenario_id,
            domain_id=block.scenario_id.split("-")[0],
            domain_name=block.domain_name,
            title=block.title,
            original_failure_class=block.original_failure_class,
            original_default_severity=block.original_default_severity,
            original_automation_label=block.original_automation_label,
            detection_description=block.fields["detection_description"],
            instrumentation_description=block.fields["instrumentation_description"],
            likely_causes=block.fields["likely_causes"],
            triage_description=block.fields["triage_description"],
            potential_remediation=block.fields["potential_remediation"],
            verification_description=block.fields["verification_description"],
            source_file=source_file,
            source_provenance=SourceProvenance(
                source_file=source_file,
                source_sha256=source_sha256,
                heading_line=block.heading_line,
                block_start_line=block.block_start_line,
                block_end_line=block.block_end_line,
            ),
            catalog_version=catalog_version,
        )
        for block in scenario_blocks
    ]
    return preamble, closing, scenarios


def _assert_no_orphan_lines(lines: list[str], consumed_ranges: list[tuple[int, int]]) -> None:
    """Every nonblank line must fall inside at least one consumed,
    recognized region (`consumed_ranges`, each an inclusive 0-indexed
    (start, end) pair). A blank line outside any region is normal
    formatting and is never flagged; a NONBLANK line outside every
    region -- injected between scenario blocks, or trailing after the
    closing guidance section -- is a hard `ParseError` naming the
    exact line, never silently ignored."""
    consumed: set[int] = set()
    for start, end in consumed_ranges:
        consumed.update(range(start, end + 1))
    for idx, line in enumerate(lines):
        if idx in consumed:
            continue
        if line.strip():
            raise ParseError(f"line {idx + 1}: unexpected content outside any recognized document section: {line!r}")


def _parse_preamble(lines: list[str]) -> tuple[CatalogPreamble, int]:
    if not lines[0].startswith("# "):
        raise ParseError(f"line 1: expected the document H1 title, got {lines[0]!r}")
    title = lines[0][2:].strip()

    def _labeled_paragraph(start_idx: int, label: str) -> tuple[str, int]:
        _require_blank(lines, start_idx, f"preamble before {label!r}")
        content_idx = start_idx + 1
        prefix = f"**{label}:**"
        if not lines[content_idx].startswith(prefix):
            raise ParseError(f"line {content_idx + 1}: expected a {prefix!r} paragraph, got {lines[content_idx]!r}")
        return lines[content_idx][len(prefix) :].strip(), content_idx + 1

    purpose, next_idx = _labeled_paragraph(1, "Purpose")
    use_safely, next_idx = _labeled_paragraph(next_idx, "Use safely")
    field_guide, next_idx = _labeled_paragraph(next_idx, "Field guide")

    _require_blank(lines, next_idx, "preamble before 'Shared reliability foundation' heading")
    heading_idx = next_idx + 1
    if lines[heading_idx].strip() != "## Shared reliability foundation":
        raise ParseError(f"line {heading_idx + 1}: expected '## Shared reliability foundation', got {lines[heading_idx]!r}")
    _require_blank(lines, heading_idx + 1, "'Shared reliability foundation' heading")
    shared_foundation = lines[heading_idx + 2].strip()
    if not shared_foundation:
        raise ParseError(f"line {heading_idx + 3}: expected the 'Shared reliability foundation' paragraph body")

    preamble = CatalogPreamble(
        title=title,
        purpose=purpose,
        use_safely=use_safely,
        field_guide=field_guide,
        shared_reliability_foundation=shared_foundation,
    )
    return preamble, heading_idx + 2


def _locate_domain_headings(lines: list[str]) -> dict[int, str]:
    """Maps heading line index -> domain name for every '## ' heading
    that is not one of the two known non-domain sections. The parser
    deliberately does NOT hardcode the 40 real domain names (it
    discovers structure from the file, it does not assume it) -- so an
    unexpected extra '## ' heading is recorded here as if it were a
    domain. `parse_source` then cross-checks every such heading
    against the scenario blocks actually found: a heading attached to
    zero scenarios is a hard `ParseError` (every real domain in this
    source has scenarios under it), and a heading that does pick up
    scenarios still surfaces as a domain-count/per-domain-count
    mismatch in `catalog.validation.validate_catalog`. Either way, an
    unexpected heading is never silently dropped."""
    domain_headings: dict[int, str] = {}
    for idx, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        name = line[3:].strip()
        if name in _NON_DOMAIN_SECTION_HEADINGS:
            continue
        domain_headings[idx] = name
    return domain_headings


def _parse_closing(lines: list[str]) -> tuple[CatalogClosing, int, int]:
    try:
        heading_idx = next(i for i, l in enumerate(lines) if l.strip() == "## Implementation guidance")
    except StopIteration as exc:
        raise ParseError("expected a closing '## Implementation guidance' section, none found") from exc

    _require_blank(lines, heading_idx + 1, "'Implementation guidance' heading")
    items: list[str] = []
    idx = heading_idx + 2
    item_re = re.compile(r"^\d+\. (.+)$")
    while idx < len(lines) and lines[idx].strip():
        m = item_re.match(lines[idx])
        if not m:
            raise ParseError(f"line {idx + 1}: expected a numbered guidance item, got {lines[idx]!r}")
        items.append(m.group(1))
        idx += 1
    if not items:
        raise ParseError("'Implementation guidance' section has no numbered items")
    closing = CatalogClosing(heading="Implementation guidance", guidance_items=items)
    return closing, heading_idx, idx - 1


def _parse_all_scenario_blocks(lines: list[str], domain_headings: dict[int, str]) -> list[ParsedScenarioBlock]:
    sorted_domain_lines = sorted(domain_headings)

    def _domain_for_line(scenario_heading_line: int) -> str:
        candidates = [dl for dl in sorted_domain_lines if dl < scenario_heading_line]
        if not candidates:
            raise ParseError(f"line {scenario_heading_line + 1}: scenario heading appears before any domain heading")
        return domain_headings[max(candidates)]

    blocks: list[ParsedScenarioBlock] = []
    for idx, line in enumerate(lines):
        if not line.startswith("### "):
            continue
        m = _HEADING_RE.match(line)
        if not m:
            raise ParseError(f"line {idx + 1}: malformed scenario heading {line!r} (expected '### D##-F## — Title')")
        scenario_id, title = m.group(1), m.group(2).strip()
        domain_name = _domain_for_line(idx)

        _require_blank(lines, idx + 1, f"{scenario_id}: after heading")
        class_line = lines[idx + 2]
        class_match = _CLASS_RE.match(class_line)
        if not class_match:
            raise ParseError(f"{scenario_id} (line {idx + 3}): malformed Class/Severity/Automation line: {class_line!r}")
        failure_class, severity, automation = (s.strip() for s in class_match.groups())

        _require_blank(lines, idx + 3, f"{scenario_id}: after Class/Severity/Automation line")

        fields: dict[str, str] = {}
        offset = 4
        for key in _BULLET_ORDER:
            bullet_idx = idx + offset
            if bullet_idx >= len(lines):
                raise ParseError(f"{scenario_id}: source ended before the {key!r} bullet was found")
            bullet_match = _BULLET_RES[key].match(lines[bullet_idx])
            if not bullet_match:
                raise ParseError(
                    f"{scenario_id} (line {bullet_idx + 1}): expected the {key!r} bullet, got {lines[bullet_idx]!r}"
                )
            fields[key] = bullet_match.group(1).strip()
            offset += 1

        block_end_line = idx + offset  # exclusive, 0-indexed
        blocks.append(
            ParsedScenarioBlock(
                scenario_id=scenario_id,
                domain_name=domain_name,
                title=title,
                original_failure_class=failure_class,
                original_default_severity=severity,
                original_automation_label=automation,
                fields=fields,
                heading_line=idx + 1,
                block_start_line=idx + 1,
                block_end_line=block_end_line,
            )
        )
    return blocks
