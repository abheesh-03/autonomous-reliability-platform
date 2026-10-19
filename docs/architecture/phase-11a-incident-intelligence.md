# Phase 11A: general-purpose incident intelligence foundation

## 1. Why Phase 11A exists, and what it deliberately is not

Phases 0-10 built and verified a complete, real-stack AI-assisted
reliability loop (alert ingestion through human-approved remediation)
plus a deterministic offline evaluation harness. Phase 11A adds a
**reference knowledge and coverage-tracking foundation** on top of
that loop: an 800-scenario incident catalog, a taxonomy-quality audit
process, a general-purpose (non-catalog-dependent) finding contract, a
detector-capability registry, an honest coverage model, and an
explicit security/policy boundary.

Phase 11A is explicitly **not**:

- live anomaly detection (no detector in `catalog/registry/` actually
  processes a real signal -- every entry is `implemented=False`);
- an exhaustive failure list (the 800 scenarios, and the ~19 detector
  families, are both documented as a *starting*, non-exhaustive set);
- a set of hardcoded rules an agent must match (`FailureFinding`,
  Gate D, is valid with zero catalog matches -- matching is always
  optional, never required);
- permission to execute remediation (Gate G: the catalog's own
  `original_automation_label` field can never authorize an action;
  the existing Phase 8/9 deterministic remediation/approval system
  remains the sole authority).

No file under `services/**`, `database/**`, `observability/**`,
`knowledge/**`, or `evals/**` was modified to build this phase. See
section 12 for the exact file list.

## 2. Source, provenance, and the Gate A audit

The real source is `catalog/source/40-domains-800-scenarios.md`
(8,900 lines), placed in the repository before this phase began. It
was read in full and empirically audited (not assumed) before any
schema or parser code was written:

- 42 total `## ` headings; 40 are real domains, 2 are the known
  non-domain sections (`Shared reliability foundation`,
  `Implementation guidance`).
- Exactly 800 `### D##-F##` scenario headings; every domain has
  exactly 20, with clean, gapless `D01-F01..D40-F20` numbering.
- Exactly 20 distinct `original_failure_class` values across all 800
  scenarios (e.g. `Resource exhaustion`, `Latency / capacity`,
  `Scheduling / batch windows`, ... the full list is embedded in
  `catalog/reviews/audit.py`'s own derived vocabulary at runtime, not
  hardcoded here, to avoid the two ever drifting apart).
- Exactly 3 distinct `original_default_severity` values
  (`Critical`/`High`/`Medium` -- no `Low`) and exactly 3 distinct
  `original_automation_label` values (`Guarded automatic action`,
  `Human approval required`, `Investigate / propose fix`).
- Every one of the 800 scenario blocks matches one exact, unvarying
  10-line shape (heading, blank, Class/Severity/Automation line,
  blank, 6 fixed-order bullets) with **zero** structural exceptions --
  confirmed programmatically against the real file before the parser
  was written, which is why the parser (section 3) is strict and
  position-based rather than fuzzy.
- Each of the 20 failure classes has a **fixed, single-template**
  `detection_description`/`instrumentation_description`/
  `likely_causes` (exactly 1 distinct variant per class, modulo a
  scenario-specific title substitution), while `potential_remediation`
  has 2-4 template variants per class. This is the objective,
  data-derived basis for the Gate C audit (section 5) -- the "class
  signature vocabulary" is read FROM the source's own template text,
  never invented.
- The catalog's own severity vocabulary (`Critical|High|Medium`) does
  **not** match the existing `reliability.incidents` table's real
  severity vocabulary (`critical|warning|info`, from
  `incident-domain-model.md`). This mismatch is deliberately never
  coerced or hidden anywhere in this phase -- see section 13.

## 3. Schema and normalization (Gate B)

`catalog/importer/parser.py` is a deterministic, line-position-based
parser: any deviation from the exact expected shape (a missing bullet,
a reordered field, a malformed heading, an unexpected `## ` heading
with zero scenarios under it) is a hard `ParseError` naming the exact
line and content -- never a silent skip, never an LLM-filled guess.

Each scenario normalizes to a `ScenarioRecord`
(`catalog/schemas/scenario.py`) preserving, verbatim, all of:
`scenario_id`, `domain_id`, `domain_name`, `title`,
`original_failure_class`, `original_default_severity`,
`original_automation_label`, `detection_description`,
`instrumentation_description`, `likely_causes`, `triage_description`,
`potential_remediation`, `verification_description`, `source_file`,
`source_provenance` (source file, sha256, exact heading/block line
range), and `catalog_version`. Every model uses
`ConfigDict(extra="forbid")`.

`catalog/validation/validate.py` separately enforces the expected
*structure* (exactly 800 scenarios, exactly 40 domains, exactly 20 per
domain, unique ids, valid `D01..D40`/`F01..F20` ranges, no blank
required fields, manifest counts matching the real lists) -- kept
deliberately separate from parsing, so "does this file have the right
shape" and "does this file match this format at all" are two
independently testable questions.

`catalog/importer/build.py` orchestrates parse -> normalize -> write,
using a fixed `"deterministic-build"` sentinel instead of a wall-clock
timestamp specifically so the version-controlled build artifact
(`catalog/build/catalog.v1.json`) is byte-for-byte reproducible run to
run -- confirmed via two independent builds and a `diff`.

**Import integrity result (real source, this phase):** 800/800
scenarios imported with no loss, 40/40 domains at 20/20 each, 0
duplicate ids, 0 validation violations, build output identical across
repeated runs.

## 4. Taxonomy quality audit (Gate C)

`catalog/reviews/audit.py` runs three independent, documented
heuristics against the built catalog, each producing
`TaxonomyReviewEntry` records (`catalog/schemas/review.py`) --
**never** a `ScenarioRecord` mutation:

1. **Class/title mismatch.** A small, curated set of
   `DomainIndicatorCategory` entries (e.g. `billing_subscription_
   lifecycle`, `account_state_lifecycle`, `fraud_risk_decisioning`,
   `security_credential_incident`), each naming a set of terms and the
   failure classes that set is semantically incompatible with. A
   scenario is flagged only when **at least two** distinct indicator
   terms co-occur in its own title AND its class is in that category's
   incompatible set -- deliberately more than single-word matching, to
   avoid a one-generic-word false positive.
2. **Safety-critical automation label.** Any scenario in a sensitive
   domain (`catalog/policy/boundary.py`'s `SENSITIVE_DOMAINS`, verified
   to be a subset of the real 40 domain names) carrying the source's
   most permissive label (`Guarded automatic action`) is flagged for
   explicit human confirmation.
3. **Vague observability (length proxy).** Flags classes whose shared
   `instrumentation_description` template is shorter than this
   corpus's own mean word count across all 20 classes -- a crude,
   corpus-RELATIVE proxy (never an arbitrary absolute cutoff), labeled
   everywhere as exactly that.

**Result on the real catalog:** 67 `REVIEW_REQUIRED` findings (3
class/title mismatches, 51 safety-critical-label flags, 13
vague-observability flags). All three named Gate C audit examples are
confirmed flagged:

| scenario | original class | flagged? |
|---|---|---|
| D01-F16 (subscription charged after cancellation) | Resource exhaustion | yes |
| D02-F10 (dormant account reactivated) | Scheduling / batch windows | yes |
| D04-F06 (fraud scoring flags legitimate claims) | Latency / capacity | yes |

A clearly coherent control scenario (D01-F01) is confirmed **not**
flagged by the class/title heuristic. Every finding defaults to
`review_status=REVIEW_REQUIRED`, carries a `heuristic_id` and full
rationale, and `suggested_correction` is always `None` from the
heuristic itself -- only a human reviewer may ever populate it.

## 5. Failure intelligence contract (Gate D)

`catalog/schemas/finding.py` defines `FailureFinding`, deliberately
**without a top-level `scenario_id` field** -- confirmed by
`test_finding_has_no_top_level_scenario_id_field`. The only link to
the catalog is `candidate_known_scenario_matches: list[
CandidateScenarioMatch]`, which may be empty, and which never, by
itself, resolves `unresolved_classification` (which defaults to
`True` even when a candidate match exists).

Six explicitly separate stages: `Observation` (evidence, never proof
of root cause), `Hypothesis` (a candidate explanation with a stated
confidence, never a conclusion), `DiagnosticCheck` (`read_only=True`
by construction), `RemediationProposal` (`requires_human_approval=
True` by default, and nothing in this schema can set it otherwise),
`Execution` (records that an *already-approved* action ran through the
existing Phase 8/9 system -- this schema does not grant or perform
execution), and `RecoveryVerification` (independent confirmation,
never assumed from the execution outcome alone).

## 6. Detector family registry (Gate E)

`catalog/registry/detector_families.py` lists 19 starting families
(availability, API errors, latency, resource saturation, process
health, deployment regressions, DB performance, DB integrity,
concurrency/idempotency, data freshness, async event processing, queue
saturation/DLQs, business invariants, auth anomalies, upstream
dependency failures, distributed trace anomalies, incident
correlation, configuration/credential failures, monitoring blind
spots). Every entry has `implemented=False` -- confirmed by
`test_no_family_claims_to_be_implemented` -- and each names its
intended signals, required/optional telemetry, prerequisites,
expected observation schema, supported categories, known gaps, and a
planned (not run) verification approach. A new family can be added
without touching any of the 800 scenarios (confirmed by
`test_new_detector_family_can_be_added_without_modifying_scenarios`).

## 7. Coverage and capability evidence (Gate F)

`catalog/schemas/coverage.py` + `catalog/coverage/tracker.py` track 8
independent dimensions per scenario: `catalogued`, `taxonomy_
reviewed`, `instrumented`, `detector_implemented`, `detection_
validated`, `investigation_validated`, `remediation_supported`,
`recovery_verification_validated`. `catalogued` is the **only**
dimension derived from catalog membership alone; every other
dimension requires an explicit `CapabilityEvidence` record (a test
reference, detector-implementation reference, integration fixture,
acceptance result, reviewed policy identifier, or recovery-
verification artifact) -- submitting evidence for `catalogued` itself
is rejected (`CoverageError`), as is evidence for a scenario id that
is not actually in the catalog.

**Honest coverage result on the real catalog, with zero detector
evidence recorded (the true current state of this phase):**

| dimension | count / 800 |
|---|---|
| catalogued | 800 |
| taxonomy_reviewed | 0 |
| instrumented | 0 |
| detector_implemented | 0 |
| detection_validated | 0 |
| investigation_validated | 0 |
| remediation_supported | 0 |
| recovery_verification_validated | 0 |

This is not a bug and is not "detection failure" -- it is the correct,
honest report for a phase that built the reference catalog and the
tracking machinery but implemented zero real detectors. Gaps are
reported as `"no scenario has recorded evidence for dimension X yet"`,
never as a failure claim.

## 8. Security and remediation policy boundary (Gate G)

`catalog/policy/boundary.py` asserts, in one place,
`automation_label_trust_level(...)` always returns
`UNTRUSTED_DOCUMENTATION` -- for every real label in the catalog,
**including** `Guarded automatic action` specifically (confirmed by
`test_guarded_automatic_action_label_specifically_is_still_
untrusted`). `FORBIDDEN_ACTION_CATEGORIES` names the 9 categories no
scenario text may ever be read as granting (payment movement, refund
issuance, destructive database writes, credential changes, access
changes, arbitrary code execution, infrastructure mutation, physical
actuator control, medical decision automation). `SENSITIVE_DOMAINS`
(14 of the real 40 domain names -- banking/fintech, healthcare/
medtech, cybersecurity, aviation/aerospace, energy/industrial/
robotics, government/regulatory) is confirmed to actually intersect
the real catalog's own domain names, so it cannot silently drift out
of sync. This module does not modify, call, or depend on the real
Phase 8/9 remediation/approval system -- it only gives that boundary a
single, named, testable assertion point for Phase 11B and beyond to
import.

## 9. Validation and negative controls (Gate H)

`catalog/tests/` (90 tests total, after the correction round in
section 14) covers every required demonstration:
all 800 scenarios import without loss; exactly 40 domains at 20 each;
no duplicate ids; an out-of-range id (`D41-F01`) fails validation; a
missing/blank required field fails validation; an unexpected empty
`## ` heading fails parsing (never silently dropped); build output is
byte-deterministic; fields are traceable to real source line ranges;
the three named misclassifications are flagged while a coherent
scenario is not; source automation labels never authorize execution
(including the `Guarded automatic action` edge case); a `FailureFinding`
with no `scenario_id` field and zero candidate matches is valid; an
unknown incident's `unresolved_classification` stays `True` even with
a candidate match present; a `RemediationProposal` always defaults to
requiring human approval; missing capability evidence produces zero
coverage (never invented partial credit); a new detector family can be
registered without touching the 800 scenarios; an intentionally
corrupted source file makes `build_catalog` raise `BuildError`
(nonzero CLI exit); an intentionally deleted scenario block is caught
as a per-domain count mismatch. All fixtures are synthetic
(`catalog/tests/fixtures/valid_minimal.md`, programmatically mutated
in-test) -- no real incident, database row, or remediation path is
ever touched.

## 10. CLI and CI (Gate I)

`python -m catalog {build,validate,audit,coverage}` -- see
`catalog/cli/commands.py` for the exact flags and exit codes (0 on
success; 1 on a parse/build/validation/coverage failure). `make
catalog-validate` runs the full offline suite via
`scripts/verify-incident-catalog.sh` (Python 3.13 in a disposable
`python:3.13-slim` container, mirroring the Phase 10
`verify-evals-offline.sh` pattern exactly); `make catalog-audit` /
`make catalog-coverage` run the individual CLI subcommands the same
way. CI runs the test suite and all four subcommands natively
(Python already set up for Phase 10's own step), placed immediately
after Phase 10's offline gate and still before the expensive
Docker/Compose acceptance section -- no existing CI step was removed
or weakened, and the job's global `timeout-minutes: 90` was not
changed (this phase's own steps run in well under a minute).

Generated-file classification: `catalog/build/catalog.v1.json`,
`catalog/build/taxonomy_review.v1.json`, and `catalog/build/
coverage_report.v1.json` (the CLI's own default output paths) are
version-controlled, reviewable artifacts. Anything written to a
non-default `--output` path is an ignored local report
(`catalog/build/local/`, `catalog/build/*.local.json` in `.gitignore`).
Note: the pre-existing generic `build/` and `coverage/` `.gitignore`
patterns were unanchored and would otherwise have also swallowed
`catalog/build/` and the real `catalog/coverage/` *source* package
(`tracker.py`) -- both are now explicitly un-ignored, with only the
genuine local-report paths above re-ignored.

## 11. What is actually implemented vs. not

**Implemented, tested, and verified against the real source this
phase:** source parsing/normalization/validation, the taxonomy audit
heuristics, the finding contract schema, the detector family registry
(as a capability description, not a detector), the coverage tracking
model, the policy boundary assertions, the CLI, and CI wiring.

**Explicitly NOT implemented (by design, this phase):** any detector
that processes a real signal; any live anomaly detection; any
automatic classification of a real incident against the catalog; any
automatic taxonomy correction (every Gate C finding is `REVIEW_
REQUIRED`, never auto-applied); any change to the real Phase 8/9
remediation/approval authority; any database migration or schema
change to `reliability.incidents`.

## 12. Files added or modified

All changes are confined to: `catalog/**` (new), `docs/architecture/
phase-11a-incident-intelligence.md` (new, this file),
`scripts/verify-incident-catalog.sh` (new), `Makefile` (3 new targets
+ help text + `.PHONY` entries appended), `.github/workflows/ci.yml`
(3 new steps inserted between the existing Phase 10 steps and the
existing "Create runtime .env" step; nothing removed), `.gitignore`
(one new section; existing entries untouched). No file under
`services/**`, `database/**`, `observability/**`, `knowledge/**`, or
`evals/**` was read-write touched (only read, for the architecture
review in Gate A). The independent-review correction round (section
14) touched only files under `catalog/**`, this doc, and
`scripts/verify-incident-catalog.sh` -- CI, Docker Compose,
`Makefile`, and `.gitignore` were not modified again.

## 13. Known limitations and open questions for Phase 11B

- **Severity vocabulary mismatch**: the catalog's `Critical/High/
  Medium` vs. `reliability.incidents`' real `critical/warning/info`
  has no reconciliation here -- any future mapping must be an explicit,
  reviewed decision, never a silent coercion.
- **Detector families are descriptions, not code**: Phase 11B's first
  real work is implementing an actual detector against real telemetry
  for at least one family, and recording real `CapabilityEvidence` for
  it (closing the `detector_implemented`/`detection_validated` gap
  honestly, scenario by scenario).
- **Taxonomy findings are unreviewed**: all 67 Gate C findings are
  still `REVIEW_REQUIRED` -- a human reviewer pass (setting
  `review_status`/`reviewer`/`reviewer_confirmed`) is Phase 11B-or-
  later work, not done here.
- **Candidate scenario matching is unimplemented**: `CandidateScenarioMatch`
  is a schema only; no matching logic (keyword, embedding, or
  otherwise) exists yet, and none is implied to exist.
- **Dependency graphs, business-invariant engines, trace analysis, and
  incident correlation** are registry descriptions only (section 6) --
  Phase 11B's own scope, not claimed here as done.
- **Read-only follow-up investigation** (`DiagnosticCheck`) is a
  schema with `read_only=True` by construction, but no runner that
  actually executes a check against a live system exists yet; building
  one is explicitly out of this phase's scope and must preserve the
  same read-only guarantee when it is built.

## 14. Independent review correction round

An independent review of the Phase 11A archive reproduced four
concrete problems against the actual code (not hypothetical) and this
round fixes all four, in `catalog/**` only (plus this doc and one
script).

1. **Safety-constrained flags accepted `False`.** `RemediationProposal.
   requires_human_approval` and `DiagnosticCheck.read_only` were typed
   `bool = True` -- a default that could still be explicitly overridden
   to `False` and pass validation, contradicting both fields' own
   documented contract. **Root cause:** `bool` instead of a type that
   actually forbids the other value. **Fix:** both are now
   `Literal[True] = True` (`catalog/schemas/finding.py`) -- an explicit
   `requires_human_approval=False` or `read_only=False` is now a
   `ValidationError`. Both models remain purely descriptive and are
   still not wired into the real remediation executor.
   Negative controls: `test_remediation_proposal_rejects_explicit_
   false_human_approval`, `test_diagnostic_check_rejects_explicit_
   false_read_only` (`catalog/tests/test_finding_contract.py`).

2. **Fabricated coverage evidence counted as valid.** `compute_coverage`
   trusted every submitted `CapabilityEvidence` record at face value --
   a nonexistent `evidence_reference` (e.g.
   `"nonexistent-file-does-not-exist.py::test_fake"`) still advanced
   `detection_validated` from 0 to 1. **Root cause:** no verification
   boundary existed between a SUBMITTED claim and a VALIDATED one.
   **Fix:** new `catalog/coverage/verification.py` introduces
   `verify_evidence()`, a fail-closed check with three outcomes --
   `VERIFIED`, `UNVERIFIABLE` (no trustworthy automated checker exists
   yet for this evidence kind, e.g. `ACCEPTANCE_RESULT`/`REVIEWED_
   POLICY_IDENTIFIER`/`RECOVERY_VERIFICATION_ARTIFACT`/
   `INTEGRATION_FIXTURE`), and `REJECTED` (a real, failed check: a
   `TEST_REFERENCE` must name a specific `path::test_name` node id that
   pytest itself can actually collect -- a bare file path is rejected
   as insufficiently specific; a `DETECTOR_IMPLEMENTATION_REFERENCE`
   must name a registered family whose own `implemented` flag is
   `True`, and since every Phase 11A family is `implemented=False`,
   this correctly rejects all such evidence today; a dimension/
   evidence-kind mismatch, e.g. a recovery artifact submitted for
   `taxonomy_reviewed`, is rejected outright). `compute_coverage`
   (`catalog/coverage/tracker.py`) now counts ONLY `VERIFIED` evidence
   toward `dimension_counts`/`coverage_by_domain`/
   `coverage_by_detector_family`, and `CoverageReport` gained
   `submitted_evidence_count`/`verified_evidence_count`/
   `unverifiable_evidence_count`/`rejected_evidence` so the distinction
   between a claim and a validated fact is never lost. No
   `verified=True` bypass field exists anywhere in the schema.
   Negative controls: `catalog/tests/test_coverage_verification.py`
   (14 tests, including the literal reported reproduction) plus two
   updated tests in `test_coverage.py`.

3. **Source parser silently ignored orphan text.** Inserting an
   arbitrary nonblank line between two valid scenario blocks did not
   affect parsing at all -- `parse_source` only checked for the
   presence of expected structures, never the ABSENCE of anything
   unexpected between them. **Root cause:** no accounting of which
   source lines were actually consumed by a recognized region.
   **Fix:** `parse_source` (`catalog/importer/parser.py`) now builds
   the exact set of 0-indexed line ranges consumed by the preamble,
   every domain heading, every scenario block, and the closing
   guidance section, then `_assert_no_orphan_lines` raises `ParseError`
   naming the exact line for any NONBLANK line outside all of them --
   legitimate blank-line formatting (confirmed against the real
   source's own style) is never flagged. `_parse_preamble` and
   `_parse_closing` were extended to also return their consumed line
   ranges. Negative controls: `test_orphan_line_between_scenario_
   blocks_fails_parsing_clearly`, `test_orphan_line_still_raises_even_
   though_scenario_count_stays_800_on_real_source` (reproduces the
   exact case against the real 8,900-line source, not just the tiny
   fixture), `test_trailing_content_after_closing_guidance_fails_
   parsing_clearly`, and a non-regression check,
   `test_legitimate_blank_line_formatting_is_still_accepted`
   (`catalog/tests/test_parser_and_validation.py`).

4. **Incomplete build returned success.** Deleting one complete
   scenario block from a copy of the source made `build_catalog()`
   return a 799-scenario manifest with no error, and `python -m
   catalog build` exited 0 and wrote the incomplete artifact -- only
   the separate `validate` subcommand caught the problem. **Root
   cause:** `build_catalog` never ran Gate B's own structural
   validation, and the CLI's `build`/`audit`/`coverage` subcommands
   never called it. **Fix:** new `build_and_validate_catalog()`
   (`catalog/importer/build.py`) composes `build_catalog` +
   `validate_catalog`, raising `BuildError` on any structural
   violation; `catalog/cli/commands.py`'s `build`, `audit`, and
   `coverage` subcommands now all call it (never plain
   `build_catalog`) before writing any artifact. `build_catalog` alone
   is deliberately left validation-free, preserving the documented
   ability for focused unit tests to construct an intentionally
   incomplete manifest directly (`test_build_catalog_alone_still_
   returns_the_incomplete_manifest`). `validate` itself still calls
   `build_catalog` directly so its own itemized, per-violation
   reporting is unaffected (confirmed by a non-regression test). New
   file `catalog/tests/test_build_validation_gate.py` (8 tests) proves,
   via real CLI subprocess invocations against a copy of the real
   source missing one scenario block: `build` exits nonzero and writes
   nothing to a fresh output path; a PRE-EXISTING artifact at the
   output path is left byte-identical (sha256-compared) when `build`
   fails; `audit` and `coverage` likewise exit nonzero and write
   nothing; and the real, complete 800-scenario source still builds
   and writes successfully (non-regression).

**Validation after this round:** 90/90 `catalog/tests` pass (up from
61); `scripts/verify-incident-catalog.sh` re-run clean end to end in a
fresh container, including explicit demonstrations of fix 2 (fabricated
evidence rejected, not counted) and fix 4 (a 799-scenario source fails
`build` and writes nothing); `git diff --check` and `git status
--short` confirm no file outside `catalog/**`, this doc, and
`scripts/verify-incident-catalog.sh` changed in this round; the real,
complete catalog still builds, validates, audits, and reports coverage
exactly as before (800/800, 40/40, zero violations, 67 taxonomy
findings, all-zero coverage beyond `catalogued`).

### 14.1 Final evidence-trust-boundary correction

A further review of fix 2 (section 14, item 2) found it was still too
permissive: `pytest --collect-only` succeeding, or a detector registry
entry carrying `implemented=True`, were both being treated as
sufficient for `VERIFIED`. Neither is -- a collectible test node
proves only that it EXISTS, never that it was EXECUTED or that its
assertions are about the claimed `scenario_id`; `implemented=True` is
self-reported registry metadata, never an independent implementation
audit. **Fix:** `catalog/coverage/verification.py` now requires an
explicit `independent_verifier` callback (`Callable[[CapabilityEvidence],
bool]`, the documented Phase 11B extension point) to be supplied AND
to confirm the claim before either signal can reach `VERIFIED`; with
no callback (Phase 11A's real CLI and tests never supply one),
collection success and `implemented=True` both resolve to
`UNVERIFIABLE` instead. `REJECTED` is unchanged for fabricated/
nonexistent references, unregistered families, and families the
registry affirmatively marks `implemented=False` for a dimension that
requires one. `compute_coverage` threads the same optional
`independent_verifier` parameter through. No untrusted reference is
ever executed -- the only subprocess call remains `pytest
--collect-only` (collection, not execution), and no catalog SOURCE
text is ever passed to a subprocess anywhere in this package.

Five new/updated negative controls prove the tightened boundary:
`test_existing_but_unexecuted_pytest_test_is_unverifiable_not_verified`,
`test_existing_test_unrelated_to_the_claimed_scenario_is_unverifiable`,
`test_registered_implemented_family_alone_is_unverifiable_without_
independent_proof` (also proves the hook genuinely works: a verifier
returning `True` reaches `VERIFIED`, one returning `False` does not),
plus the preserved `test_fabricated_test_reference_rejected_directly_
by_verifier` (nonexistent reference) and
`test_evidence_can_reach_verified_only_through_the_independent_
verifier_hook`/`test_unverifiable_evidence_is_reported_but_never_
counted_toward_coverage` (valid-but-unverified claims never counted).

**Validation after this round:** 92/92 `catalog/tests` pass (up from
90); `scripts/verify-incident-catalog.sh` re-run clean end to end;
`git diff --check`/`git status --short` confirm only `catalog/**`,
this doc, and `scripts/verify-incident-catalog.sh` changed; the real
catalog's coverage report is unchanged (800/800 catalogued, all seven
other dimensions at 0/800 with zero evidence submitted) -- now on an
even stricter, honestly-grounded basis than before.
