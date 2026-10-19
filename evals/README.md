# Phase 10: AI evaluation and reliability benchmarking

A deterministic, offline, versioned evaluation harness for this
platform's AI surfaces (investigator-service's evidence-grounded
investigation, retrieval-service's RAG retrieval, agent-runtime-
service's remediation-decision policy). See
`docs/architecture/phase-10-ai-evaluation.md` for the full design
record; this file is the practical "how do I run/extend this" guide.

## 1. What this is

A test suite that calls the REAL, unmodified production functions
from `investigator-service`, `retrieval-service`, and
`agent-runtime-service` directly (editable-installed as Python
packages) against a versioned set of hand-reviewed cases, and reports
`PASS` / `FAIL` / `NOT_EVALUATED` for each one. It never reimplements
citation validation, retrieval ranking, investigation classification,
or remediation policy -- see `docs/architecture/phase-10-ai-evaluation.md`
section 5 for the exact production functions each scoring module
calls.

## 2. What this is NOT

- Not a live dashboard. A CLI plus JSON/Markdown reports only.
- Not a semantic-quality proof for a real LLM. The default (and only
  CI-required) mode is fully deterministic and offline -- see the
  optional real-model mode (`scoring/real_model.py`) for the one,
  narrow, explicitly-opt-in exception.
- Not a re-proof of control-plane's own atomic approve/reject
  transaction safety (that needs a real database; see
  `services/control-plane/tests/test_remediation_transactions.py`) or
  tool-gateway's own compiled-in allowlist (that's Go, proven by its
  own Go test suite and Phase 8's live acceptance script).
- Not a mutation of any production service, incident, or remediation
  state. Nothing under `services/**` is modified by this phase.

## 3. Directory layout

```
evals/
  README.md                    this file
  requirements.txt             this harness's OWN minimal deps (pytest, pytest-asyncio)
  pyproject.toml                pytest config only (asyncio_mode) -- not a distributed package
  datasets/v1/manifest.json     dataset version + provenance summary
  datasets/v1/regression_baseline.json   recorded PASS/FAIL per case_id
  cases/v1/*.json               the versioned, reviewable case files
  scoring/                      one module per evaluation_mode, each reusing real production code
  fakes/                        minimal duck-typed doubles for agent-runtime-service's clients (offline-only)
  runner/                       the CLI (`python -m evals.runner`), loader, report writer
  tests/                        the harness's OWN unit/negative-control test suite
  reports/                      generated JSON/Markdown output (gitignored, regenerated every run)
```

## 4. Dataset provenance and versioning

Every case file lives under `evals/cases/<dataset_version>/` and
carries its own `dataset_version` field, which must match the
directory (enforced by the loader). `evals/datasets/<version>/manifest.json`
records when that version was created, its category breakdown, and a
provenance summary.

Each case's own `provenance.kind` is one of:

- `"real_corpus"` -- built directly from a real, source-controlled
  file (today: `knowledge/runbooks/*.md`, used by the two retrieval
  cases). Never a synthetic document.
- `"synthetic"` -- hand-constructed to mirror a real contract/shape
  (e.g. a realistic `EvidencePackage`), but not captured from a real
  incident. **Every synthetic case says so explicitly in its own
  `provenance.notes`** -- a synthetic case is never presented as
  observed production truth.
- `"real_fixture"` -- reserved for a future case built from a real,
  anonymized production artifact, if one is ever added.

## 5. Ground-truth labeling strategy

Every case's `expected_outcome` and `ground_truth_rationale` was
written by a human against this platform's own ALREADY-DOCUMENTED
contracts -- `classify_investigation`'s own docstring,
`llm/validation.py`'s own module docstring, `graph/nodes.py`'s own
policy comments and constants, and the real `knowledge/runbooks/*.md`
files themselves. **No case's expected answer was generated or graded
by asking an LLM to judge its own output** -- that would make the
harness circular (the thing being measured would also be the judge).
`ground_truth_rationale` always names the specific real contract rule
the expectation follows from, so a reviewer can check the claim
without re-deriving it.

## 6. Metrics and their limitations

- **Citation validity** (`scoring/citation.py`): exact, deterministic
  pass/fail -- an id either survived validation or did not. No
  "confidence score."
- **Retrieval relevance** (`scoring/retrieval.py`): `hit_at_k` (0/1)
  and `reciprocal_rank` per case; the runner aggregates these into a
  mean Hit@k and MRR across all retrieval cases in a run. Computed via
  the deterministic LOCAL LEXICAL embedding provider
  (`retrieval_service.embeddings.provider.LocalLexicalEmbeddingProvider`)
  over the real runbook corpus -- this is a feature-hashing model with
  no notion of word meaning or synonyms. **It proves the deterministic
  ranking pipeline's own contract, never the semantic quality of the
  real, configured OpenAI embedding model production actually uses.**
  With only 4 real runbooks in the corpus today, `top_k` must be kept
  smaller than the corpus size for a "this should NOT be retrieved"
  case to be expressible at all (see RET-007's own comment).
- **Investigation quality** (`scoring/investigation_quality.py`): a
  single three-way label (`well_supported`/`partial`/`inconclusive`)
  from the REAL `classify_investigation` function, plus one narrow
  rubric check (no `confidence="high"` hypothesis may have empty
  `supporting_evidence_ids`). **This module makes no attempt at
  open-ended hallucination detection on free text** -- it would be
  dishonest to claim a deterministic score for that; see Gate C's own
  explicit instruction.
- **Remediation safety** (`scoring/remediation_safety.py`): binary,
  hard pass/fail outcomes (was a proposal created, was execute()
  called, what final status resulted) from driving the REAL
  `agent_runtime_service.graph.build.compile_graph` with
  `InMemorySaver` and minimal fake clients. No semantic judgment at
  all -- every one of these cases is a structural safety check.
- **Adversarial/deterministic** (`scoring/adversarial_deterministic.py`):
  proves ONLY that hostile, delimiter-shaped text is rendered as
  escaped, inert data by `build_prompts`. It says nothing about
  whether a real model would obey an embedded instruction that uses no
  delimiter-shaped character at all -- see section 7's real-model
  mode for that distinct question, which this module explicitly does
  not answer.

## 7. Safety invariants vs. soft quality metrics

Every case sets `is_hard_safety_invariant`. A **hard** invariant
(e.g. "rejection must never execute", "an ineligible incident must
never produce a proposal", "a fabricated citation must never survive")
failing always fails the whole run (`RunReport.exit_code()` returns
1) and is listed in the report's own `safety_violations`. A **soft**
quality case (e.g. an investigation-quality classification, a
retrieval hit) failing is reported and contributes to `failed`, but
is tracked separately so a safety regression can never be buried
among ordinary quality drift.

**`NOT_EVALUATED` always fails the run too** (`RunReport.exit_code()`),
regardless of whether the case that could not run was hard or soft --
a measurement that was skipped is an INCOMPLETE benchmark, never a
passing one. This is never achieved by folding a `NOT_EVALUATED` case
into `safety_violations` itself (that list stays reserved for
genuinely DETECTED hard-FAIL violations, never a fabricated one for a
measurement that simply never ran).

**A real bug this dataset's own construction caught**: RET-007
originally used `top_k=5` against a 4-document corpus, which made
"this must NOT be retrieved" structurally impossible to express (every
document is trivially "in the top-5" when only 4 exist) -- the
harness's own full-suite run surfaced this immediately as an
unexpected failure, and it was fixed by tightening `top_k` to 2. This
is recorded here, honestly, as an example of catching a meaningless
assertion rather than hiding it.

**A second real bug an independent review caught**: `RunReport.exit_code()`
originally did not check `not_evaluated` at all, `_select_cases()`
could silently select zero cases for an unknown `--case-id`/`--category`,
`evals/datasets/v1/manifest.json` declared `remediation_safety: 6`
when only 5 such cases actually exist on disk (its own category counts
summed to 16 while `total_cases` said 15), and `regression.py` tracked
only PASS/FAIL/NOT_EVALUATED outcomes, never numeric metrics -- so a
retrieval ranking could quietly degrade (e.g. `reciprocal_rank`
1.0 → 0.5) while `require_hit` stayed satisfied and the case kept
reporting PASS. All four are fixed (§8's manifest validation, this
section's `exit_code()` fix, Issue 2's selector validation, and §6's
own metric-drift reporting) -- recorded here so the dataset's own
history stays honest rather than silently rewritten.

## 7a. Manifest validation and dataset completeness

`evals/datasets/<version>/manifest.json` is no longer a passive
description -- it is validated on every run:

- **Internal consistency** (checked on EVERY run, filtered or not):
  `categories` must sum to exactly `total_cases`. This is the exact
  check that would have caught the `remediation_safety: 6` bug above
  before it ever shipped.
- **Full-dataset completeness** (checked ONLY on an unfiltered run --
  no `--case-id`/`--category` given): `dataset_version`, `total_cases`,
  per-category counts, and the explicit `case_ids` list must all
  exactly match the real, loaded case files. A case file removed from
  disk without updating the manifest, or added without declaring it,
  fails the run -- never silently ignored. A deliberately filtered
  (subset) run is NOT held to this standard, by design -- see §2 of
  the final correction-pass note above.

## 7b. Numeric metric drift (soft, never gates CI)

The regression baseline (`evals/datasets/v1/regression_baseline.json`)
now records each case's own measured `metrics` (e.g. a retrieval
case's `hit_at_k`/`reciprocal_rank`), not just its PASS/FAIL/NOT_EVALUATED
outcome. Every run compares current metrics against the baseline and
reports any drift (`RunReport.metric_drift`) -- in BOTH the JSON and
Markdown reports -- even when the case's own outcome is unchanged.
This is purely informational: there is no invented accuracy threshold,
and metric drift never affects `exit_code()`. Only genuine PASS/FAIL/
NOT_EVALUATED outcome regressions (`RunReport.regression_findings`,
particularly a HARD safety invariant one) can ever fail a run.

A **required** baseline file is now STRICT for an ordinary run: a
missing or malformed baseline (or one for the wrong `dataset_version`)
fails the run outright -- it never silently falls back to "no
baseline, nothing to compare, everything passes". `--update-baseline`
is the one, explicit, separate bootstrap/refresh path: it tolerates a
genuinely MISSING baseline file (first-time setup), but still rejects
a malformed/wrong-version one, and it refuses to overwrite the
existing baseline unless THIS run was itself fully successful
(`RunReport.is_fully_successful()` -- no FAIL, no NOT_EVALUATED, no
safety violation). An incomplete or failed run can never replace the
reviewed reference baseline.

**Two further bugs an independent review caught, both fixed (never
weakened to pass)**:

1. A metric the baseline recorded for a case (e.g. a retrieval case's
   `reciprocal_rank`) that simply DISAPPEARS from a later run's own
   output (a scorer regression, a code change) used to be silently
   skipped by `compare_metrics_to_baseline` -- an incomplete
   measurement could look like a clean benchmark. Fixed by
   `evals/scoring/regression.py::apply_missing_metric_checks`, called
   before pass/fail/not_evaluated counts are computed: it downgrades
   that ONE case's own result to `NOT_EVALUATED` (naming the specific
   missing metric in its detail), reusing the exact same
   `exit_code()` machinery every other incomplete measurement already
   goes through -- never a fabricated `0.0` value, never added to
   `safety_violations`. `compare_metrics_to_baseline` itself is
   unchanged and intentionally stays narrow (pure drift computation
   among metrics present in both places); completeness is this
   separate function's own job.
2. `--update-baseline` used to accept a filtered (`--case-id`/
   `--category`) run, so a single-case run could silently overwrite
   the complete, reviewed dataset baseline. Fixed: `--update-baseline`
   combined with either filter is now rejected OUTRIGHT, before any
   file is even opened -- the existing baseline file is left
   byte-for-byte untouched. `--update-baseline` only ever takes effect
   for a complete, unfiltered, manifest-validated, fully successful
   run.

## 8. Running locally

Requires Docker (to run a `python:3.13-slim` container with this repo
bind-mounted -- the same convention `make investigator-test`/
`make retrieval-test`/`make agent-runtime-test` already use, so results
are reproducible regardless of your own host Python version):

```
make eval-offline
```

or directly:

```
./scripts/verify-evals-offline.sh
```

If you already have Python 3.13 natively:

```
pip install -e services/investigator-service -e services/retrieval-service -e services/agent-runtime-service
pip install -r evals/requirements.txt
python -m evals.runner
python -m pytest evals/tests -c evals/pyproject.toml -v
```

Useful flags on `python -m evals.runner`:

- `--case-id CIT-008` (repeatable) -- run only specific case(s)
- `--category remediation_safety` (repeatable) -- run only a category
- `--update-baseline` -- record this run's own results as the new
  regression baseline (an explicit, reviewable action -- never done
  implicitly)
- `--real-model` -- see section 9
- `--json-out PATH` / `--markdown-out PATH` -- override report
  locations (default `evals/reports/latest.{json,md}`, gitignored)

## 9. Real-model mode (optional, never required)

```
INVESTIGATOR_LLM_API_KEY=sk-... python -m evals.runner --real-model
```

Re-runs a bounded subset (at most `MAX_REAL_MODEL_CASES`, currently
10) of `citation`-mode cases against a REAL, configured OpenAI
provider, using the exact same `build_prompts`/`parse_and_validate`
pipeline the offline mode uses. **Never invoked by default, never
required for CI, never network-capable unless you explicitly pass
`--real-model` AND have a real `INVESTIGATOR_LLM_API_KEY` configured**
(`INVESTIGATOR_LLM_PROVIDER=stub` does NOT count as "real" here, even
though it satisfies the service's own `configured` property -- this
mode checks the stronger condition itself). Results are reported
SEPARATELY from the deterministic offline PASS/FAIL/safety-violation
counts (a real model's output is stochastic; it must never gate CI or
this run's own exit code) and record the real model identifier and
run timestamp in the report's `real_provider` field. A provider
failure (timeout, empty response) is `NOT_EVALUATED`, never scored as
quality success. This mode only ever reports **citation validity**
of the real model's own output -- it makes no semantic-correctness
claim; see section 6.

## 10. Reading reports

`evals/reports/latest.json` and `evals/reports/latest.md` (gitignored,
regenerated every run). The Markdown report leads with dataset
version, pass/fail/not-evaluated counts, safety violations, regression
findings, a full per-case table, retrieval MRR/Hit@k (when retrieval
cases ran), and this run's own `limitations` list -- read that last
section before trusting any number above it.

## 11. Adding a new case

1. Pick the right `evaluation_mode` (see `scoring/__init__.py`'s
   `SCORERS` map) -- add a new scoring module only if none fits.
2. Write a new `evals/cases/v1/<CATEGORY>-<NNN>-<slug>.json` (or bump
   to a new `v2` directory + manifest if you're changing the dataset's
   own meaning, not just adding a case within it).
3. Fill every field the `Case` schema requires
   (`evals/scoring/models.py`) -- `ground_truth_rationale` must name
   the specific real contract rule your expectation follows from, and
   `provenance.kind`/`notes` must be honest about whether this is
   real-corpus, synthetic, or a real fixture.
4. Run `python -m evals.runner --case-id YOUR-NEW-ID` to check it in
   isolation before running the full suite (a filtered run like this
   one is never held to full-dataset manifest completeness -- see §7a).
5. Update `evals/datasets/v1/manifest.json`: bump `total_cases`, the
   new case's own category count, and add its `case_id` to the
   `case_ids` list -- an unfiltered run will otherwise fail outright
   on the completeness mismatch (§7a), by design.
6. Run the full, unfiltered suite (`python -m evals.runner`) to
   confirm the updated manifest now validates and every case passes,
   then `--update-baseline` to record the new case's own real,
   measured result (and any metrics) -- never hand-edit
   `regression_baseline.json` directly.

## 12. What Phase 10 does NOT prove

- It does not prove a real LLM produces correct, useful investigations
  in general -- only that THIS harness's bounded citation check passes
  for whatever real or stub output it was given (see section 6).
- It does not prove real semantic retrieval quality -- only the
  deterministic lexical pipeline's own ranking contract (section 6).
- It does not prove a real model resists a prompt-injection attempt
  that uses no delimiter-shaped character -- only that delimiter-
  shaped hostile text is rendered as escaped data by the real
  deterministic renderer (section 6, `adversarial_deterministic`).
- It does not re-prove control-plane's own real-database atomic
  approve/reject transaction safety, or tool-gateway's own compiled-in
  Go allowlist -- both are proven by their own existing test suites
  and Phase 8's real, live acceptance script, not duplicated here.
- It does not measure latency, cost, or throughput of any real
  provider.
- Passing this harness is NECESSARY evidence of correct deterministic
  behavior, never SUFFICIENT evidence that the overall AI system is
  "good" -- it is one layer of a larger reliability story, not the
  whole of it.
