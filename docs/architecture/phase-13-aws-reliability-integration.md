# Phase 13: AWS production reliability integration

## 1. Actual architecture

Phase 13 extends the existing platform with a fourth observation source
(alongside Alertmanager, the Kubernetes observer, and the existing
Prometheus/Tempo telemetry pipeline): a bounded, read-only AWS observer that
reuses every existing durable-ingestion, evidence-collection, and
investigation mechanism rather than inventing a parallel one.

```
detectors/aws/            (Gate 1/2) bounded, read-only AWS observation + deterministic detection
  detectors/clients/aws_client.py   AwsClientProtocol (mockable) + Boto3AwsClient (real, live)
  detectors/aws/collector.py        bounded pagination/outcome classification per AWS API
  detectors/aws/detectors.py        deterministic CloudWatch/EC2/ECS classifiers (pure functions)
  detectors/aws/findings.py         AwsDetectionFinding -> catalog.schemas.finding.FailureFinding
  detectors/aws/publisher.py        opt-in POST to control-plane's AWS ingestion endpoint

detectors/pipeline/       (Gate 3) orchestrator.py/run.py additively wire in an optional aws_client
detectors/cli/commands.py (Gate 3) --aws-observe + explicit account/region/enrollment opt-in

services/control-plane/   (Gate 4) a SEPARATE auth boundary + ingestion path, reusing the SAME
  api/aws.py                        incident repository / audit-trail / fingerprint-lock /
  ingestion/aws_service.py          occurrence-watermark / transaction patterns Phase 12B-D
  ingestion/aws_mapping.py          already established for Kubernetes -- never a parallel
  domain/aws_finding.py             incident architecture.

services/investigator-service/ (Gate 5) evidence_collector.py grows one more best-effort,
  bounded, redacted, source-attributed evidence branch (source == "aws")

services/web-console/     (Gate 5) reused AS-IS -- see section 7 below; zero code change.

infra/aws/                (Gate 6) Terraform + IAM preparation; creates nothing by default.
```

An AWS-sourced incident lands in the SAME `reliability.incidents` table, is
visible through the SAME unauthenticated read API and web console, and is
investigated through the SAME `EvidencePackage`/LLM pipeline as every other
incident source. Nothing here is a second reliability platform.

## 2. Database migration

One additive migration, `V9__add_aws_incident_actor.sql`, widens
`reliability.incident_events.actor_type` to also accept `'aws'` -- the exact
same shape of change `V8__add_kubernetes_incident_actor.sql` already made for
`'kubernetes'`. V1-V8 are untouched. `'aws'` is accepted for `created`/
`observed` events only; `status_transition` remains restricted to
`'alertmanager'`/`'operator'` (an AWS-sourced incident can only ever be
created/observed by this path, never resolved by it -- see Gate 4 below).

As a direct side effect of widening this one `Literal` field correctly, the
Python `IncidentEvent.actor_type` domain model (`domain/incident_event.py`)
was also widened to include `'kubernetes'`, which had been a pre-existing gap
since Phase 12B-D (the database already accepted it; the Pydantic model did
not, which would have raised a validation error on `GET
/api/v1/incidents/{id}/events` for any incident with a Kubernetes-actor
event). This is now consistent for both sources.

## 3. Gate 1: the AWS observer

`detectors/clients/aws_client.py` defines `AwsClientProtocol` -- the ONE
mockable seam the rest of the package depends on -- and `Boto3AwsClient`, the
real `boto3`/`botocore`-backed implementation. Every method on the Protocol
is one of exactly 8 read-only AWS calls:

- `sts:GetCallerIdentity` (account verification, before any observation)
- `cloudwatch:DescribeAlarms`, `cloudwatch:GetMetricData` (opt-in, cost-bounded)
- `cloudtrail:LookupEvents`
- `ec2:DescribeInstances`, `ec2:DescribeInstanceStatus`
- `ecs:ListServices`, `ecs:DescribeServices`

No mutating action exists anywhere in this module (`detectors/tests/
test_aws_client.py`/`test_safety_controls.py` structurally assert this).
`AwsObserverScope` requires an explicit, validated account id, region, and
resource enrollment (alarm names / instance ids / ECS cluster-or-service
pairs) -- `describe_alarms`/`describe_instances`/`describe_instance_status`
all raise `AwsConfigError` outright if called with no enrollment, rather than
ever falling back to "describe everything". `verify_identity()` calls STS and
raises `AwsIdentityMismatchError` on any account mismatch; the pipeline
orchestrator treats this as blocking the WHOLE AWS stage for that run, never
just one check.

Every call is wrapped in bounded timeouts/retries (`botocore.config.Config`)
and classified into one of `AwsCollectionOutcome`'s SUCCESS / EMPTY / PARTIAL
/ MALFORMED / UNAVAILABLE / FORBIDDEN / THROTTLED / NOT_FOUND -- never
silently treated as healthy. CloudTrail's own raw `CloudTrailEvent` JSON blob
(which can carry `requestParameters`/`responseElements`/session context) is
never read at all; only the bounded, structurally safe summary fields
(`EventId`/`EventName`/`EventTime`/`EventSource`/`Username`/`Resources[]
.ResourceName`) are kept -- redaction by omission, never a regex that could
miss something.

## 4. Gate 2: deterministic AWS failure detection

`detectors/aws/detectors.py` implements the 4 required detection cases as
pure functions over already-collected observations:

1. **CloudWatch alarm state**: `StateValue == "ALARM"` -> CONFIRMED (with the
   real state timestamp/reason as evidence); `"INSUFFICIENT_DATA"` ->
   INSUFFICIENT_EVIDENCE; `"OK"` -> no finding at all.
2. **EC2 status checks**: only evaluated for explicitly enrolled instances,
   and only while `state_name == "running"` -- `stopped`/`stopping`/
   `shutting-down`/`terminated`/`pending` produce NO finding at all
   (intentional shutdowns are never misclassified). `impaired` -> CONFIRMED;
   `insufficient-data`/missing status evidence -> INSUFFICIENT_EVIDENCE.
3. **ECS desired-vs-running degradation**: `desired_count in (None, 0)` is
   excluded entirely. A shortfall during an `IN_PROGRESS` rollout ->
   INSUFFICIENT_EVIDENCE (a deployment genuinely takes time); a shortfall with
   a `FAILED` rollout, or a sustained shortfall with no rollout in progress,
   -> CONFIRMED.
4. **CloudTrail supporting evidence**: a bounded, formatted list of nearby
   management events sharing a resource identifier is attached to a finding
   as `supporting_change_events` -- ALWAYS alongside an explicit
   `uncertainty_notes` stating that temporal proximity does not establish
   causation. CloudTrail evidence never produces a finding on its own.
5. **Insufficient/unavailable evidence**: a failed/forbidden/throttled/
   malformed collection is propagated into the pipeline's `checks_not_executed`
   list and NEVER used to run the corresponding detector at all (see
   `_USABLE_AWS_OUTCOMES` in `orchestrator.py`) -- never silently treated as
   "zero findings therefore healthy".

Detection and causal explanation stay separate: `AwsDetectionFinding` never
asserts a root cause, only an observed symptom plus bounded supporting
evidence. AWS findings are built into `catalog.schemas.finding.FailureFinding`
exactly like every other detector family (`detectors/aws/findings.py`), and
are deliberately NEVER submitted to the cross-system correlation engine (see
`orchestrator.py`'s own docstring) -- a real AWS account and this stack's
sandbox/docker-compose services share no real trace id, fingerprint, or
observed dependency edge.

## 5. Gate 3: pipeline integration

`detectors/pipeline/orchestrator.py`/`run.py` grow one more optional
`aws_client` parameter, following the EXACT same pattern Kubernetes
established in Phase 12A: no client supplied -> an honest
`("aws_observation", "no AWS client was supplied")` entry in
`checks_not_executed`, never a hidden failure, and the rest of the pipeline
is completely unaffected either way.

`detectors/cli/commands.py` adds `--aws-observe` (the deliberate live
opt-in), `--aws-account-id`, `--aws-region`, `--aws-profile`, four
`--aws-enroll-*` repeatable flags, `--enable-aws-get-metric-data` (off by
default), and `--publish-aws-findings-to-control-plane` (opt-in, token read
only from `CONTROL_PLANE_AWS_INGESTION_TOKEN` in the environment, never a CLI
argument). `--aws-observe` requires account id + region + at least one
resource enrollment all together, mirroring the existing
`--kubeconfig`/`--kube-context`/`--kube-namespace` "all or nothing" rule
exactly.

**Offline replay**: `python -m detectors replay --fixture ...` never included
Kubernetes either (confirmed by reading `cli/fixture_loader.py` and
`cli/commands.py`'s own `_cmd_replay` before writing this phase) -- Phase 12A
satisfied "deterministic offline replay" via a Python-level fake
`KubernetesClient` driving the real pipeline in
`test_kubernetes_pipeline_integration.py`, not via the CLI's JSON fixture
mechanism. Phase 13 follows the identical, already-established precedent:
`detectors/tests/test_aws_pipeline_integration.py` and
`test_aws_collector_bounds.py` drive the real `run_pipeline`/
`collect_and_detect`/`detectors.aws.collector` code against a plain
`FakeAwsClient`, fully offline, deterministically. `replay`'s existing
behavior (Prometheus/Tempo/control-plane fixtures) is completely unmodified
and was re-verified byte-identical across two runs.

## 6. Gate 4: durable AWS incident ingestion

`services/control-plane/src/control_plane/{api,ingestion,domain}/aws_*.py`
mirror the Kubernetes ingestion path's structure field-for-field:

- **Separate auth boundary**: `CONTROL_PLANE_AWS_INGESTION_TOKEN`
  (`require_aws_ingestion_token`) is a SEVENTH, independent secret --
  `resolve_write_tokens`'s own pairwise-collision guard now covers it
  against all six others, including the Kubernetes ingestion token
  specifically (tested explicitly in `test_aws_ingestion.py` and
  `test_config.py`).
- **Fingerprint**: `(account_id, region, resource_kind, resource_id,
  detector_id)`, hashed -- distinguishes AWS account, region, resource
  identity, and failure class exactly as required, while an ARN change alone
  (e.g. instance replaced with the same id reused across a different launch)
  never splits the SAME ongoing operational concern into two incidents.
- **Occurrence/freshness**: reuses `get_active_incident`/
  `get_most_recent_incident`/`acquire_fingerprint_lock`/
  `upsert_firing_incident` UNCHANGED (these were already source-agnostic);
  the SAME `MAX_FUTURE_SKEW_SECONDS`/`MAX_PAST_STALENESS_SECONDS` discipline
  rejects future-dated and stale evidence outright (422), before any
  occurrence decision is made.
- **Never auto-resolves**: there is no `_process_resolved_finding` for AWS,
  same as Kubernetes -- an alarm disappearing, or any AWS API returning an
  empty response, is never treated as recovery. Only the existing
  authenticated operator lifecycle endpoint can transition status.
- **Cross-source policy negative control**: `agent-runtime-service`'s
  `propose_remediation` deterministic policy only ever matches
  `source == "alertmanager"` (payment) or `source == "kubernetes"` -- an
  `"aws"`-sourced incident falls through to `not_applicable`
  *unconditionally*, regardless of either capability's own precondition
  state. This is now covered by an explicit test
  (`test_aws_sourced_incident_never_authorizes_payment_or_kubernetes_remediation`)
  rather than resting on inference alone.

## 7. Gate 5: investigator + web console integration

`investigator_service.evidence_collector.EvidenceCollector` grows one more
best-effort, bounded, redacted, source-attributed branch
(`_collect_aws_evidence`), reached only when `incident.source == "aws"`,
reading the new `GET /api/v1/incidents/{id}/aws-evidence` endpoint via a new
`ControlPlaneClient.get_aws_evidence` method. The ONE produced `EvidenceItem`
answers every one of Gate 5's required questions directly: WHAT symptom was
observed (`detector_id`/`result`), WHICH resource (`account_id`/`region`/
`resource_kind`/`resource_id`/`resource_arn`), WHEN it was collected
(`collected_at`), WHETHER CloudTrail offers a relevant preceding change event
(`supporting_change_events`, rendered with an explicit "temporal proximity
alone does not establish causation" caveat in the item's own detail text),
and WHAT remains missing (`collection_completeness`, mapped to the SAME
`"ok"`/`"partial"`/`"unavailable"`/`"no_data"` `SourceOutcome` vocabulary
every other source already uses).

**Web console**: reused as-is, with **zero code change**. Verified by
inspection before writing any UI code: `lib/types/incident.ts`'s `Incident.
source` is already a bare `string` (never a restricted union), and both
`app/incidents/page.tsx` and `app/incidents/[incidentId]/page.tsx` already
render `incident.source`/`incident.title` generically. Because
`map_aws_finding_to_incident_fields` embeds `account_id`/`region`/
`resource_kind`/`resource_id` directly into the incident's own `title` field
(exactly the same technique the Kubernetes path already uses for
cluster/namespace/resource), an AWS-sourced incident already displays a
meaningful, accurate label through the existing generic rendering -- adding a
dedicated AWS UI component was evaluated and judged unnecessary scope for
this phase's own stated goal ("if the existing UI allows a small additive
change" -- it does, and that change is the title-embedding done entirely on
the control-plane side, not in `web-console/`).

AWS remediation remains READ-ONLY/recommendation-only: no AWS executor, no
approval bypass, and no cloud-resource-mutation code path exists anywhere in
this phase.

## 8. Gate 6: Terraform and IAM preparation

See `infra/aws/README.md` for the full write-up (evidence trust limitations,
which permissions require `Resource: "*"` and why, region/account
conditions, cost discussion, and the future provisioning checklist). In
summary: `infra/aws/terraform/` is a parameterized module whose every
resource is gated behind `enable_provisioning` (default `false`) and whose
`data "aws_iam_policy_document"` resources are pure, local, offline JSON
renders -- no AWS API call. `terraform fmt`/`terraform validate` were run
successfully against this module (via a local `terraform` binary, provider
plugin downloaded from the public Terraform registry -- not an AWS API call);
`terraform apply` has never been run, and no real account id/credential
exists anywhere in the directory.

## 9. Gate 7: cost and safety

No live AWS SDK call was made at any point while implementing or testing this
phase. Every automated test (`detectors/tests/test_aws_*.py`,
`services/control-plane/tests/test_aws_ingestion.py`,
`services/investigator-service/tests/test_aws_evidence_integration.py`)
uses either a plain in-test fake implementing `AwsClientProtocol` or
`httpx.MockTransport` -- `Boto3AwsClient` (the only code path that can ever
reach a real AWS endpoint) is never constructed anywhere in this test suite,
confirmed structurally by `test_safety_controls.py`'s own checks. CI remains
AWS-credential-free: `boto3`/`botocore` are build-time dependencies only.
`GetMetricData` is disabled by default at the `Boto3AwsClient` constructor
level (`enable_get_metric_data=False`), independently re-asserted by a
dedicated structural test.

## 10. Security and trust boundaries

- **Credential isolation**: the AWS ingestion token, the Kubernetes ingestion
  token, and every other write-endpoint token in control-plane are seven
  mutually non-interchangeable secrets, enforced by the same
  constant-time-comparison + pairwise-collision-detection mechanism Phase
  3C/8/12B-D already established.
- **Identity verification before observation**: `Boto3AwsClient.
  verify_identity()` is the first AWS call the pipeline ever makes in a live
  run; a mismatch blocks the entire AWS stage for that run.
- **No automatic remediation authorization**: an AWS-sourced incident can
  never reach either the payment or Kubernetes remediation branch of
  `propose_remediation` -- this is a property of the deterministic
  `source`-based policy dispatch, not a runtime check that could be bypassed.
- **Redaction**: CloudTrail's raw event JSON is never read; every other
  free-text field (`decision_rationale`, `supporting_change_events`) passes
  through the same `redact()` function every other untrusted-text field in
  this platform already uses.

## 11. Known limitations / NOT IMPLEMENTED

- **CompositeAlarms** are not collected or classified -- only `MetricAlarms`.
  A documented, deliberate scope limitation, not an oversight.
- **GetMetricData** is implemented at the client level but is not wired into
  any of the 4 required detectors -- it exists as the "explicitly opt-in,
  with small limits" observation API Gate 1 itself describes, available for
  a future detector to use, never exercised in this phase's own detection
  logic.
- **CloudTrail `error_code`** is always `None` in this phase's own collector
  -- `LookupEvents`' event summary does not expose it directly, and this
  process deliberately never parses the raw `CloudTrailEvent` blob to find
  it (see the redaction-by-omission discussion in section 3).
- **No background scheduler**: exactly like the Kubernetes observer, this CLI
  has no daemon mode. A single `analyze` invocation is one bounded,
  point-in-time check; repeated observation is an operator's own, separately
  visible decision (e.g. an external cron job), never something this process
  claims to do on its own.
- **No live-cluster/live-account proof in this round**: every test is
  offline/mocked, per Gate 7's explicit restriction. A future, separately
  human-authorized live smoke test is documented in `infra/aws/README.md`'s
  checklist but has not been performed.
- **No multi-tenant AWS account onboarding UI** -- explicitly out of scope
  for this phase per the brief; this remains a single, explicitly configured
  account/region per run.
