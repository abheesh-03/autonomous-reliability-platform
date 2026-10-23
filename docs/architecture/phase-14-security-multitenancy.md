# Phase 14 — Secure Authentication, Organizations, RBAC, Tenant Isolation

## Final machine-identity tenant-boundary fix round

A third round, after the final security blocker correction round and
the final test stabilization round below. An independent reviewer
reproduced two more real cross-tenant gaps directly from the current
source, both sharing the same root cause: **resolving a resource's
real owning organization is not the same as authorizing the caller
for that organization.** A third, related gap was reviewed across the
remaining machine write-side endpoints. This section documents the
EXACT machine-authorization boundary as it now stands.

### Issue A — retrieval-service: resolving ≠ authorizing

`search._resolve_historical_organization_scope` (Blocker 2) correctly
derives a historical-incident search's tenant scope from the REAL
owning organization of `exclude_incident_id` — but, until this round,
it never checked WHO was asking. Any holder of
`RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR` (a single, global,
transport-level credential) could name ANY existing incident id and
receive that incident's owning organization's historical results,
regardless of which organization the real request was actually about.

**Fix:** retrieval-service now also verifies an optional, relayed
`X-Service-Assertion` (`retrieval_service/authz.py`, new —
`trusted_issuers={"investigator-service"}`, `audience="retrieval-service"`,
same HS256 verification discipline as every other service).
investigator-service's `RetrievalClient` relays a derived assertion
(ADDITIVE to the existing static token, never a replacement) naming
the real actor bound for the current request
(`investigator_service.authz.current_actor()`/`sign_derivative_assertion`,
the SAME mechanism Blocker 1 already built one hop earlier for its own
control-plane client). `_resolve_historical_organization_scope` now
requires BOTH facts to hold before returning any historical result:
(1) `exclude_incident_id` resolves to a real incident (Blocker 2,
unchanged), AND (2) the relayed actor's own `organization_id` matches
that incident's real owning organization exactly. Missing either fact
→ no historical search at all (empty results, never an HTTP error;
global `knowledge` results are unaffected either way). Legacy/local-dev
mode (enforcement disabled) is explicitly isolated from this
requirement — the pre-Phase-14 client-supplied `organization_id`
behavior is preserved byte-for-byte.

### Issue B — control-plane: a global static token is not a tenant grant

`core/authz.py::get_actor_or_tool_gateway_reader` let tool-gateway's
bare `X-Internal-Service-Token`, presented ALONE with no actor
assertion at all, read ANY already-decided remediation proposal
regardless of which organization owned it. The proposal's decided
STATUS proved WHEN it became readable; it never proved WHO was asking
was entitled to that specific tenant's data.

**Fix:** the bare-token-alone fallback is REMOVED. Tool-gateway now
relays — unverified by itself; it holds no copy of the shared HS256
signing secret — the SAME `X-Service-Assertion` agent-runtime-service
gives it when telling it to execute a specific proposal
(`agent_runtime_service.clients.tool_gateway.py`'s own
`_headers()`, ADDITIVE to the unchanged `TOOL_GATEWAY_EXECUTION_TOKEN`
Bearer auth; `services/tool-gateway/internal/controlplane/client.go`'s
new `WithServiceAssertion`, a per-request shallow client copy —
`internal/api/execute.go` creates one from the incoming request's own
header at the top of `ExecuteHandler` and uses it for every one of
its own `GetProposal`/`StartExecution`/`RecordExecutionResult` calls;
the shared, long-lived client is never mutated, so concurrent
executions for different actors never cross-contaminate). Control-
plane verifies this relayed assertion exactly like any other, and
`require_tool_gateway_proposal_access`'s existing `ActorContext`
branch — unchanged — checks the real actor's organization against the
proposal's real owning incident, exactly as it already does for a
human. A real, tenant-matched actor may now read their own
organization's still-pending proposal too (status-gating was only
ever a proxy for tenant legitimacy on the old bare-token path, never a
real requirement once a real tenant check exists). `InternalServiceContext`
and its own branch in `require_tool_gateway_proposal_access` remain in
the source, defensively, but are no longer constructible from any real
request in secure mode — presenting the bare token with no assertion
is now a 401.

### Issue C — the three machine write-side endpoints, now tenant-checked before mutation

`POST /internal/v1/remediation-proposals`,
`POST /internal/v1/remediation-proposals/{id}/execution/start`, and
`.../execution/result` relied on their existing global machine Bearer
tokens (`CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN`/
`CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN`) alone — proof of "this is
a legitimate machine caller", never proof of "this caller is entitled
to THIS tenant's incident/proposal."

**Fix (additive, same tokens still unconditionally required):** each
endpoint now ALSO accepts the relayed actor
(`Depends(get_actor_context)`, the SAME dependency `decide_remediation_proposal`
already uses) and, when one is present (secure mode), calls
`require_same_organization` against the proposal's real owning
incident's organization BEFORE any mutation —
`create_remediation_proposal` checks the TARGET incident directly;
`start_remediation_execution`/`record_remediation_execution_result`
resolve the proposal's own incident first. A mismatch is 404 (not
found), never 403, and never mutates anything — verified directly:
the fake repository's own call-tracking (`create_proposal_called`/
`start_execution_called`/`record_execution_result_called`) proves the
underlying state-machine method was never even invoked. agent-runtime-
service's `ControlPlaneClient.create_remediation_proposal` now ALSO
relays a derived assertion (previously this ONE method used only the
static proposal token, never `_internal_headers()` at all). No new
executable action, no change to the action allowlist, no change to
any atomic transition or idempotency rule — only an authorization
check inserted before each existing mutation, exactly mirroring
Blocker 4's own "recheck before mutation" discipline.

### The exact machine-authorization boundary, end to end

```
agent-runtime-service (real actor bound via get_actor_context,
                        whenever organization-context enforcement is on)
  │
  ├─→ control-plane:  create_remediation_proposal / start_execution /
  │                    record_execution_result / get_remediation_proposal
  │                    -- derived assertion relayed directly (Issue C,
  │                    Blocker 1)
  │
  ├─→ tool-gateway (execute, with the SAME assertion in its own header)
  │     │
  │     └─→ control-plane: GetProposal / StartExecution /
  │           RecordExecutionResult -- tool-gateway forwards the
  │           IDENTICAL assertion, unverified by itself (Issue B/C)
  │
  └─→ investigator-service (derived assertion, Blocker 1)
        │
        └─→ retrieval-service: search -- investigator-service relays a
              FURTHER-derived assertion (Issue A)
```

Every hop after the original web-console-minted assertion is a
`sign_derivative_assertion` call that accepts only a whole, already-
verified `ActorContext` (never a separately-suppliable org/role/user) —
confirmed by grep, not merely asserted, in the Task 2 security audit
above: the only places any service ever constructs an `ActorContext`
are inside its own `verify_service_assertion`. Tool-gateway is the one
exception in this chain that never verifies anything itself — it is a
transparent relay only, by construction (it holds no copy of the
shared secret), and control-plane is the party that actually verifies
whatever it forwards.

### What this round does NOT change

No migration, no new executable remediation action, no widened
allowlist, no change to `decide_remediation_proposal`'s own live-
membership recheck (Blocker 4) or Better Auth/session verification
(unchanged throughout). Legacy/local-development mode (organization-
context enforcement disabled) is unaffected end to end — every new
check here is gated on an actor actually being present, which only
happens once enforcement is explicitly turned on.

### Validation (this round)

Real, not merely unit-level: `scripts/retrieval_tenant_isolation_check.py`
(18/18, including the two new Issue A scenarios — a real Org A actor
denied Org B's incident's historical results by its known UUID, and
the explicit "no actor relayed at all" static-credential-alone
denial) against the live Postgres stack;
`scripts/verify-phase14-multitenant-security.sh` (34/34, unaffected,
rerun to confirm no regression); `scripts/verify-remediation.sh` — the
real Phase 8 payment-remediation acceptance — rerun end to end against
FRESHLY REBUILT `control-plane`/`agent-runtime-service`/`tool-gateway`
images actually containing this round's code (not merely the
already-running, days-old containers), in the platform's default
legacy/local-dev mode (`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT`
unset): a real checkout failure, a real human-approved proposal
created/started/recorded through the exact three Issue-C endpoints,
real tool-gateway execution via the exact Issue-B GetProposal path,
and real recovery, all still working byte-for-byte as before. The
live Kubernetes remediation acceptance script
(`verify-kubernetes-remediation-live`) is explicitly documented as
"NEVER RUN BY THIS SESSION" and was correctly not run; Kubernetes
remediation regression coverage here is unit-level only (control-
plane's and tool-gateway's own existing Kubernetes test suites, both
green, unaffected by this round's changes).

## Final security blocker correction round + final test stabilization round

Two further rounds happened after the "Correction round" below. This
section documents the architecture as it actually stands NOW — read
this section first; the "Correction round" and original Gate-by-Gate
sections below it describe how it got there, and are kept for history
rather than rewritten.

### What changed: BLOCKER 1 — the signed-assertion relay chain

The correction round's internal-service-read tokens (`CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME`
etc.) turned out to be a real tenant-isolation hole: any ONE of those
three static tokens, by itself, unconditionally bypassed
`require_same_organization` for every incident/evidence/remediation-
proposal GET — a single leaked token granted read access to every
organization's data, not just the holder's legitimate scope. That
bypass is now removed. The actual, current identity chain is:

```
Browser session (Better Auth, re-verified every request)
  │  web-console's lib/server/actor.ts::resolveActor() mints a
  │  60s-lived HS256 assertion {sub, org, role, iss:"web-console",
  │  aud:<downstream service>} -- X-Service-Assertion header.
  ▼
agent-runtime-service  (verifies iss="web-console", aud="agent-runtime-service")
  │  authz.py::bind_actor() puts the VERIFIED ActorContext into a
  │  contextvar for the request's lifetime. Its own
  │  ControlPlaneClient/InvestigatorClient read `current_actor()` and,
  │  if bound, mint a 15s-lived DERIVED assertion
  │  {sub, org, role: IDENTICAL to the bound actor, iss:"agent-runtime-service",
  │  aud:<downstream>} via sign_derivative_assertion() -- never a
  │  separately-suppliable org/role/user, only ever a whole, already-
  │  verified ActorContext object. If no actor is bound (legacy/local-
  │  dev mode), it falls back to the old static internal-read token.
  ▼                                      ▼
control-plane                   investigator-service
(aud="control-plane";            (aud="investigator-service";
 trusted_issuers includes         trusted_issuers = {"agent-runtime-service"}
 "web-console",                   ONLY -- narrower than control-plane's,
 "agent-runtime-service",         since web-console never calls it
 "investigator-service")          directly)
                                        │  Same pattern again: a relayed,
                                        │  verified actor is bound via its
                                        │  OWN contextvar, and ITS OWN
                                        │  control-plane client mints a
                                        │  FURTHER-derived assertion
                                        │  (iss="investigator-service")
                                        │  to read incident evidence on
                                        │  the relayed actor's behalf.
                                        ▼
                                  control-plane
```

Every hop's org/role/subject are copied byte-for-byte from the
PREVIOUS hop's own cryptographically-verified `ActorContext` —
confirmed directly (not merely asserted) in this round by grepping
every service's source for `ActorContext(` constructor calls: the
*only* production-code construction sites are inside each service's
own `verify_service_assertion`, and `sign_derivative_assertion`'s
signature accepts a whole `ActorContext` object plus a fixed,
pre-configured downstream audience — never separate org/role/user_id
parameters an internal service could override. There is no code path
from an incoming HTTP request to a forged or escalated derived
assertion.

tool-gateway's own static `X-Internal-Service-Token` is now the ONLY
static token that still grants anything by itself, and only for one
narrow case: reading a remediation proposal that has **already**
reached a decided status (`approved`/`rejected`/`executing`/
`succeeded`/`failed`) — never a still-`pending_approval` one, since
reaching any decided status already passed through
`decide_remediation_proposal`'s own real human-actor + live-membership
+ tenant + role check.

### The signing-key boundary, honestly (Task 2 security audit finding)

**This is the single most important thing to understand about this
design, and the thing earlier wording in this document risked
overclaiming:** `SERVICE_ASSERTION_SIGNING_SECRET` is ONE symmetric
HS256 secret, shared by all four trusted parties — web-console,
control-plane, agent-runtime-service, and investigator-service.
`trusted_issuers` and `iss` are a **labeling/audit convention layered
on top of that shared secret, not a cryptographic boundary between
those four services.** Any one of them, if its process were
compromised at the code-execution level, could mint a signed assertion
claiming to be issued by any OTHER trusted issuer, for any
organization, any role, any subject — the signature alone cannot
distinguish "really issued by investigator-service" from "forged by
whoever stole the shared secret." **Do not describe this design,
anywhere, as "distinct issuers provide isolation between these
services."** They do not. What they DO provide, and all they are
designed to provide:

- Isolation from any party that does **not** hold the shared secret —
  an external attacker, a compromised browser, a different, untrusted
  internal process. This is the actual, real boundary this design
  defends, and it holds: `verify_service_assertion` rejects an
  unsigned, wrongly-signed, wrong-audience, wrong-issuer, or expired
  token identically to no token at all (Gate 5's original guarantee,
  unchanged).
- A clear audit trail (`ActorContext.issued_by`) distinguishing an
  original web-console-minted assertion from a relayed one, for
  logging/debugging — informational, never itself a grant of
  authority.
- No *application-level* privilege-escalation path through the code
  this platform actually ships: there is no function, route, or
  argument anywhere in agent-runtime-service's or investigator-
  service's own code that accepts a client-influenced org/role/user and
  feeds it into a signing function — proven by the Task 2 audit's own
  provenance grep and by `tests/test_authz.py` in both services
  (`test_attempting_to_relay_a_higher_role_than_verified_is_not_possible_through_this_api`,
  `test_attempting_to_change_organization_during_relay_is_not_possible_through_this_api`,
  and their `_across_the_second_relay_hop` counterparts in
  investigator-service).

web-console, control-plane, agent-runtime-service, and
investigator-service are therefore best understood as **one single
trusted internal perimeter**, not four independently-verifiable
identities — this was already implicitly true before this round (the
original three-party design shared the same secret), and this round
extends that SAME existing trust model to a fourth party rather than
introducing a qualitatively new risk. A genuine per-service identity
boundary (e.g. asymmetric keypairs with a real trust store, or mutual
TLS) would be a real redesign of this mechanism — out of scope for
this correction round, which was explicitly instructed not to restart
Phase 14's design.

**Expiration/replay:** a derived assertion lives 15s (shorter than
web-console's own original 60s window) specifically to narrow this
exposure, but there is no `jti`/nonce-based replay cache anywhere in
this system — an intercepted, still-valid assertion is replayable
within its own TTL window, for an original OR a derived one, exactly
as it already was before this round. This is an accepted, pre-existing
characteristic of a stateless bearer-token design, not something this
round introduced or could narrowly fix without adding real server-side
state; it is mitigated by assuming an internal, non-public network
(this stack does not currently run TLS between internal services —
also a pre-existing, named limitation, see "Known limitations" below).

**Contextvar cleanup and concurrency:** `bind_actor`'s `__exit__`
unconditionally resets the contextvar regardless of whether the bound
code raised (Python's own `with`-statement guarantee once `__enter__`
has returned) — verified directly by
`test_bind_actor_cleans_up_even_when_the_bound_code_raises` in both
services. Because `contextvars.ContextVar` is task-local in asyncio,
and Starlette/FastAPI schedule each incoming HTTP request as its own
asyncio task, two concurrent requests for different organizations
never observe each other's bound actor — verified directly by
`test_concurrent_requests_from_different_organizations_never_cross_contaminate`
(both services), which runs two simulated requests concurrently via
`asyncio.gather` with interleaved `await asyncio.sleep(0)` yields and
asserts neither ever sees the other's actor. A task spawned WHILE an
actor is bound (e.g. deep inside a LangGraph node during
`graph.ainvoke`) correctly inherits that binding, since
`asyncio.create_task` copies the current context at creation time —
verified by `test_a_task_spawned_while_an_actor_is_bound_inherits_it_correctly`.

### What changed: BLOCKER 4 — live membership recheck + durable human-approval audit

A signed assertion's `role` claim is only ever as fresh as the moment
it was minted (up to its own TTL) — not proof that the actor is STILL
a member with that role right now. `decide_remediation_proposal` now
performs a SECOND, live, read-only check immediately before any
mutation: `AuthMembershipRepository.get_current_role()` queries Better
Auth's own `auth.member` table directly (cross-schema, `SELECT`-only
grant — `scripts/init-web-console-db.sh`), and a recently
revoked/demoted approver is rejected even while their signed assertion
remains technically unexpired. Verified for real end-to-end in
`scripts/verify-phase14-multitenant-security.sh`'s Phase 6: a real,
verified member is removed from the organization via a real Better
Auth call mid-session, and their still-unexpired session is denied on
the very next request, both for reading the incident page and for
approving a remediation proposal, with zero mutation either way.

`database/migrations/V11__add_remediation_decision_audit.sql` (additive;
**V1–V10 untouched**) adds `decided_by_user_id`/`decided_by_organization_id`
to `reliability.remediation_proposals`, populated with the REAL,
live-rechecked human actor's identity on every decision — also
mirrored into the append-only `remediation_events.metadata`. Verified
for real: the same end-to-end script's Phase 3b approves a proposal
through the actual browser-to-backend path and then reads the row back
directly from Postgres, confirming `decided_by_user_id` matches the
real signed-in user's real Better-Auth-generated id, not a placeholder.

### What changed: BLOCKER 2 — retrieval-service tenant scope

Historical-incident retrieval no longer trusts a client-supplied
`organization_id` at all once `CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT`
is on. The tenant scope is now derived server-side from the REAL owning
organization of the request's own `exclude_incident_id` (a real
Postgres lookup against `reliability.incidents`), and fails closed
(empty historical results) if that incident doesn't resolve at all —
an internal credential cannot simply name a different tenant to read
its private evidence. Global `knowledge`/runbook chunks remain
retrievable regardless of org, by the same explicit, documented policy
as before. Legacy, fully-unscoped behavior is preserved exactly when
organization-context enforcement is off. Verified against a real,
live Postgres via `scripts/verify-retrieval-tenant-isolation.sh`
(15/15 checks).

### What changed: BLOCKER 3 — invitation email ownership, fail-closed

The log-URL verification fixture (Issue 5, below) is now explicitly
scoped to local/non-secure deployments only.
`lib/auth/email-verification-delivery.ts` checks the SAME
`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` flag every other service
in this platform uses: in secure mode, with no real email-delivery
provider configured, it now **throws** rather than logging a live,
usable verification token to server logs or pretending delivery
happened — meaning invitation acceptance (which requires
`emailVerified`) is **not available at all** in a secure deployment
until a real email provider is wired in. No hardcoded bypass for any
account; no fabricated delivery. This document previously described
the log-URL fixture as a general mitigation — it is correct to
describe it as a **local-development-only** one.

### What changed: BLOCKER 5 — real browser-to-backend end-to-end coverage

The prior end-to-end script proved cross-tenant rejection only against
HAND-SIGNED JWTs posted directly to control-plane — real, but not
proof of the full browser path (it never exercised a real Better Auth
session, the Next.js BFF's own actor resolution, or its own
assertion-minting code). `scripts/verify-phase14-multitenant-security.sh`
now additionally: signs in through real Better Auth; uses the real
session cookie; explicitly selects the real organization
(`organization/set-active`); requests web-console's own real Next.js
routes (`/incidents/{id}`, `/incidents`,
`/api/remediation-proposals/{id}/decision`) and lets the BFF mint its
own assertion from that real, resolved actor — never a hand-signed
one, for every authorization-sensitive check. It also replaced a prior
negative control that only proved "the wrong static token is
rejected" with a real cross-tenant approval attempt using the
**correct, valid** static backend credential alongside a real,
authenticated, wrong-tenant actor (still correctly denied, 404, zero
mutation) — the test the independent review specifically asked for.
**34/34 checks pass** against a real, disposable
Postgres/Better-Auth/control-plane/web-console stack.

Running this for real (not merely writing it) surfaced and fixed two
genuine bugs: this script itself used the wrong control-plane URL
environment variable (misleadingly making every cross-tenant check
pass for the wrong reason — the page rendered an inline error, not a
real HTTP rejection), and a real, pre-existing bug in
`lib/server/actor.ts`: Better Auth's `auth.api.getActiveMember` throws
rather than returning a falsy value for a revoked member, which
crashed `resolveActor`/`requireActorOrRedirect` with an unhandled 500
instead of the intended fail-closed redirect/`null`. Fixed with a
`getActiveMemberOrNull` wrapper that catches exactly that one expected
`APIError` case.

### HTTP-based real-service checks vs. actual browser-driven E2E — explicitly distinguished

**What this platform actually has, and what each check proves:**

- `scripts/verify-phase14-multitenant-security.sh` (34 checks) and
  `scripts/verify-retrieval-tenant-isolation.sh` (15 checks) are real,
  disposable, HTTP-driven integration tests: real processes, real
  Postgres, real Better Auth, real HTTP requests via `curl` with real
  session cookies. They prove the real authorization DECISIONS are
  correct end-to-end, including through web-console's own server-side
  rendering path. They do **not** drive a real browser, execute any
  client-side JavaScript, or verify what a human actually sees
  rendered on screen (CSS, interactive elements, client-side state).
- A real Playwright browser E2E suite DOES exist in this repository —
  `services/web-console/e2e/phase9-workflow.spec.ts` (`npm run e2e`) —
  but it exercises Phase 9's remediation workflow against the FULL,
  live `docker compose` stack (Postgres, Prometheus, Alertmanager,
  Loki, Tempo, payment-service, tool-gateway, every backend service),
  requires sustained real traffic to make a real Prometheus alert fire
  and then naturally recover, and has its own 20-minute timeout. It is
  not specific to Phase 14's authentication/multi-tenancy work at all
  (it predates Phase 14). It was **not run** in this validation
  round — bringing up and sustaining the full multi-service stack for
  several real minutes was outside this round's practical scope, and
  no claim is made that it was run or that it passed. This is a real,
  named limitation, not a silent gap.

## Correction round (independent security review)

An independent review of the first Phase 14 submission found five real
gaps and asked for a sixth, broader verification. All five were fixed
and verified against real services/real PostgreSQL in this session;
none were dismissed or argued away.

**Issue 1 — organization id type mismatch.** Better Auth's default id
generator produces an opaque random string, not guaranteed to be a
valid UUID — incompatible with `reliability.incidents.organization_id
UUID NOT NULL`. Fixed by setting `advanced.database.generateId:
"uuid"` in `lib/auth/auth.ts` (verified against the installed
package's real type definitions: `"if postgres, we use the
gen_random_uuid() function"`). Regenerated `auth-schema/schema.sql`
against a live database and confirmed every Better Auth id column
(including `organization.id`) is now a native Postgres `uuid` column.
Also added defensive UUID parsing/validation in
`control_plane/core/authz.py::verify_service_assertion` (rejects a
non-UUID `org` claim before it can reach SQL) and in
`web-console/lib/server/actor.ts::signAssertion`. **A real, previously
undetected bug was found and fixed as a direct result of writing the
real-database test this issue required**:
`IncidentRepository.list_incidents`'s `organization_id` filter bound a
plain Python string against an untyped SQLAlchemy column, which
Postgres rejected (`operator does not exist: uuid = character
varying`) — invisible to the existing mocked-repository unit tests,
which have no SQL type system at all. Fixed by explicitly typing the
column as `PG_UUID(as_uuid=True)`. Verified end-to-end with a real
Better Auth user + organization (real generated UUID), a directly
persisted incident, and real cross-tenant GET/LIST calls against a
secured control-plane — see
`scripts/verify-phase14-multitenant-security.sh`, Phases 1–2.

**Issue 2 — unprotected evidence/resource APIs.** Audited every
control-plane, agent-runtime, investigator, and retrieval endpoint.
Found and fixed: `GET /api/v1/incidents/{id}/kubernetes-evidence` and
`/aws-evidence` (control-plane's `api/kubernetes.py` / `api/aws.py`)
had no actor/tenant check at all. Both now use the same
`get_actor_or_internal_reader` + `require_same_organization` pattern
as every other incident GET. investigator-service's own
`POST /api/v1/investigations` and retrieval-service's own
`POST /api/v1/retrieval/search` are each independently reachable on
their own exposed loopback ports (127.0.0.1:8001 / :8002),
bypassing agent-runtime-service/investigator-service entirely — both
now require their own internal-service caller token
(`require_internal_caller`, Issue 3) once secure mode is enabled, and
retrieval-service's search now accepts an optional `organization_id`
that excludes a different organization's `historical_incident` chunks
via a real SQL JOIN against `reliability.incidents` (`knowledge`/
runbook chunks remain global, by explicit policy).

**Issue 3 — internal service authentication breakage.** Enabling
`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` broke every existing
internal read call that never sent a human assertion: agent-runtime-
service → control-plane, investigator-service → control-plane,
tool-gateway → control-plane (`GetProposal`), agent-runtime-service →
investigator-service, investigator-service → retrieval-service. Fixed
with five distinct, bounded, read-only internal-service credentials
(`CONTROL_PLANE_INTERNAL_READ_TOKEN_AGENT_RUNTIME` /
`_INVESTIGATOR` / `_TOOL_GATEWAY`,
`INVESTIGATOR_INTERNAL_READ_TOKEN_AGENT_RUNTIME`,
`RETRIEVAL_INTERNAL_READ_TOKEN_INVESTIGATOR`), each checked via a
dedicated `X-Internal-Service-Token` header, never `Authorization` or
`X-Service-Assertion`. `core/authz.py::InternalServiceContext` is a
distinct type from `ActorContext` precisely so it can never reach
`decide_remediation_proposal` (which uses `get_actor_context` alone) —
a leaked internal-read token still cannot approve/reject anything.
Verified by new real-request tests in every affected service
(control-plane, investigator-service, retrieval-service, plus a Go
`client_test.go` for tool-gateway) and by the end-to-end script's
Phase 3 (an internal credential is never accepted on the decision
endpoint).

**Issue 4 — secure mode vs. legacy ingestion.** Added
`CONTROL_PLANE_ALLOW_LEGACY_INGESTION` (default `true`): when secure
mode is on, an operator can now explicitly disable the legacy,
non-tenant-aware Alertmanager/Kubernetes/AWS ingestion pipeline
(`core/authz.py::require_legacy_ingestion_allowed`, applied to all
three ingestion endpoints) rather than silently keep accepting
findings into one shared legacy organization under the false
impression that multi-tenant ingestion exists. Ingestion still has no
mechanism anywhere that reads an organization id from a payload —
confirmed by grep, not merely asserted — so "unknown integrations
assigned to arbitrary organizations" was already structurally
impossible; this flag makes the legacy-vs-real-multi-tenant boundary
an explicit, testable, documented choice instead of an implicit one.
Verified by `tests/test_legacy_ingestion_boundary.py` (webhook and
Kubernetes ingestion both fail closed, 503, with zero mutation, when
the flag is off in secure mode; both are unaffected when secure mode
is off at all).

**Issue 5 — invitation email ownership.** An unverified account could
sign up with a victim's exact email and accept an invitation addressed
to it, since sign-in itself doesn't require verification and this
console has no real email delivery (the invite link is shown directly
to the inviter, never mailed). Fixed using Better Auth's own, already-
built-in, real mechanisms — verified directly against its installed
source, never guessed: `requireEmailVerificationOnInvitation: true`
(its own docs state this should be on exactly when invitation ids
aren't mailbox-gated, which is our case) plus a real
`emailVerification` configuration (`sendOnSignUp: true`, a real
single-use token, surfaced via server logs since no provider is
configured — same honest, non-faked pattern already used for
invitations). Better Auth's own source already independently enforces
wrong-email rejection and expired/non-pending (revoked, reused)
invitation rejection; this correction only needed to add the
verified-email gate. All eight required scenarios (unverified,
verified, wrong email, expired, revoked, reused, non-admin invite,
self-role-escalation) are proven against a real Better Auth instance
in `scripts/verify-phase14-multitenant-security.sh`, Phases 4–5.

**Additional verification.** The reviewer noted the first round's
tests used fabricated JWTs and mocked repositories exclusively.
`scripts/verify-phase14-multitenant-security.sh` is a new, real,
disposable, re-runnable end-to-end test: a throwaway PostgreSQL
(never the developer's own volume), a real Better Auth instance (two
real users, two real organizations, real UUIDs), a real control-plane
instance in secure mode, direct-SQL-persisted incidents (ingestion
itself is unauthenticated/legacy-org-only, so this is the correct,
honest fixture point — see Issue 1 above), and real HTTP requests
throughout. It asserts, with real pass/fail checks (23/23 passing):
org A can access org A, org B can access org B, neither can access the
other's incident/events/remediation proposal by a real known UUID,
list/count endpoints never leak the other org's data, no rejected
request ever mutates anything, and all eight invitation-security
scenarios. The existing, more narrowly-scoped pytest suites (real
FastAPI app + crafted-but-correctly-signed JWTs + an in-memory fake
repository) remain in place as fast, CI-friendly regression coverage —
they were extended, not replaced.

## Objective and scope

Phase 14 transforms this platform from a locally-trusted, single-tenant
operator console into a multi-user, organization-aware application,
without redesigning the existing reliability architecture (incidents,
investigations, remediation, Kubernetes/AWS observation) and without
beginning Phase 15's public SaaS productization.

**Core security principle governing every decision below:**
authentication is not authorization. A valid login never, by itself,
permits reading an incident, starting an investigation, approving
remediation, or seeing another organization's data. Every
tenant-sensitive server-side operation independently verifies the real
authenticated actor's organization membership and role — never a
browser-controlled organization id, URL parameter, cookie, or
unsigned header.

This document describes what was actually implemented, how it fits
together, and — explicitly, honestly — what was deliberately deferred.
It is not a claim of exhaustive coverage of every one of the original
specification's 11 gates; it is a real, coherent, independently
verified core slice of that specification, with the remaining scope
named precisely so a reviewer can decide what to prioritize next.

## Trust-boundary map (Gate 1)

```
Browser
  │  (session cookie, HttpOnly/SameSite, Better Auth)
  ▼
web-console (Next.js BFF)
  │  - Server Components / Route Handlers re-derive the real actor on
  │    EVERY request via auth.api.getSession + auth.api.getActiveMember
  │    (lib/server/actor.ts) -- never cached, never trusted from a
  │    prior request.
  │  - Mints a short-lived (60s) HS256 "service assertion" (jose)
  │    carrying {sub, org, role}, signed with SERVICE_ASSERTION_SIGNING_SECRET,
  │    a separate audience per downstream service.
  │  - Forwards it in a DEDICATED header, X-Service-Assertion -- never
  │    `Authorization`, which several existing routes already use for
  │    a static Bearer token (CONTROL_PLANE_LIFECYCLE_TOKEN,
  │    CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN). The two are
  │    independent, additive checks on the same request.
  ▼
control-plane / agent-runtime-service
  │  - core/authz.py (both services): verifies the assertion's
  │    signature, issuer, audience, and expiry (PyJWT, pinned HS256,
  │    bounded clock skew) -- only once CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT
  │    is enabled. Disabled (the default), every route behaves exactly
  │    as it did before Phase 14.
  │  - Every tenant-sensitive route: (1) resolves the resource, (2)
  │    reads its real organization_id, (3) compares it to the verified
  │    actor's organization_id, (4) checks the actor's role against
  │    the specific action's required role set. A mismatch is 404
  │    (resource "not found"), never 403 (which would confirm the
  │    resource exists in another organization) -- except a same-
  │    tenant permission denial, which IS a 403.
  ▼
PostgreSQL (reliability schema, Flyway-owned; auth schema, Better-Auth-owned)
```

Existing, already-documented local-dev limitations this phase
integrates with rather than removes:
- Alertmanager/Kubernetes/AWS finding ingestion remains a single
  shared-token-authenticated pipeline per source, landing every
  incident in one fixed "legacy local-development organization" (see
  "Known limitations" below) — Gate 6's full per-tenant ingestion
  association is **not** implemented in this phase.
- investigator-service and retrieval-service are **not** modified in
  this phase; their own evidence/retrieval reads are not yet
  independently tenant-scoped (see "Known limitations").
- tool-gateway's own execution/recovery-verification trust boundary is
  unchanged.

## Gate 2 — Authentication

**Library:** [Better Auth](https://better-auth.com) `1.7.12` (with
`@better-auth/core` `1.7.12`, `jose` `6.2.13` as its own dependency).
Chosen per the task's own instruction to evaluate it first; every API
used in `services/web-console/lib/auth/auth.ts` was verified directly
against the real installed package's `.d.mts` type definitions and,
further, against a real running instance (see "Validation evidence"
below) — not guessed.

- Real, library-provided password hashing/session management (no
  homegrown crypto).
- `emailAndPassword` enabled, `minPasswordLength: 12`.
- Sessions: 7-day expiry, 1-day sliding update, HttpOnly/SameSite
  cookies (Better Auth's own defaults), `useSecureCookies` gated by
  `WEB_CONSOLE_USE_SECURE_COOKIES` (false for this phase's plain-HTTP
  local deployment; documented as a hard requirement once served over
  HTTPS).
- `trustedOrigins` pinned to the existing `WEB_CONSOLE_TRUSTED_ORIGIN`
  convention — **verified live**: a cross-origin mutation attempt is
  rejected with `INVALID_ORIGIN` (see evidence below). This is also
  Better Auth's own CSRF defense (no separate hand-rolled CSRF token).
- Built-in rate limiting enabled (`rateLimit: { enabled: true, window:
  60, max: 20 }`).
- Email verification / account recovery: **not implemented**. No
  external email provider is configured. `requireEmailVerification:
  false` is explicit, and the invitation flow's `sendInvitationEmail`
  callback is a safe, disabled-by-default no-op (logs server-side
  only) rather than a faked "email sent" claim. This is a named,
  deliberate limitation — see "Known limitations."
- Every protected Server Component/Route Handler calls
  `requireActorOrRedirect` / `requireActorOrUnauthorized`
  (`lib/server/actor.ts`), which re-validates the real session
  server-side on every request — Next.js middleware is **not** used as
  a security boundary (none exists in this codebase at all).

## Gate 3 — Organizations, users, memberships, roles

Better Auth's `organization` plugin is the **single authoritative
source** of users/sessions/organizations/memberships/roles — no
competing authorization database. `services/web-console/lib/auth/access-control.ts`
defines a custom access-control policy (via `createAccessControl`/
`role` from `better-auth/plugins/access`) with exactly the five roles
the task specified: `OWNER`, `ADMIN`, `ENGINEER`, `VIEWER`,
`INCIDENT_APPROVER`. `creatorRole: "OWNER"` — verified live: creating
an organization assigns the creator role `OWNER` automatically (see
evidence below).

**Authorization matrix:**

| Principal / Role     | Action                                      | Resource                     | Enforced by |
|-----------------------|----------------------------------------------|-------------------------------|-------------|
| Any authenticated user | create organization                        | organization                 | Better Auth (`allowUserToCreateOrganization`) |
| OWNER/ADMIN           | invite/remove member, change role, manage org | organization/member/invitation | Better Auth's own `ac`/`roles` (server-verified) |
| Any member            | leave organization                          | own membership               | Better Auth |
| VIEWER, ENGINEER, INCIDENT_APPROVER, ADMIN, OWNER | read incident / events / remediation proposals in own org | incident | control-plane `core/authz.py::require_same_organization` |
| ENGINEER, ADMIN, OWNER | create / resume agent run (start investigation) | agent run / incident | agent-runtime-service `authz.py::ROLES_THAT_MAY_RUN_INVESTIGATIONS` |
| VIEWER, INCIDENT_APPROVER | **cannot** create/resume agent run        | agent run                    | agent-runtime-service (403) |
| OWNER, INCIDENT_APPROVER | approve/reject remediation proposal       | remediation proposal / incident | control-plane `authz.py::ROLES_THAT_MAY_DECIDE_REMEDIATION` |
| ADMIN, ENGINEER, VIEWER | **cannot** approve/reject remediation proposal (even in own org) | remediation proposal | control-plane (403) |
| Any role, any org     | **cannot** read/mutate another org's incident, run, or proposal | any tenant resource | 404 (control-plane / agent-runtime-service) |
| Internal service credential (webhook/lifecycle/remediation/ingestion tokens) | ingest / lifecycle-transition / propose / execute | incident / proposal | existing static Bearer tokens (`api/auth.py`), unchanged |

Membership/role data is durable (Better Auth's own `member`/
`invitation` tables, FK'd to `organization`/`user` with `ON DELETE
CASCADE`). No self-promotion path exists (role changes go through
`updateMemberRole`, itself gated by Better Auth's own `ac`). Last-owner
removal, invitation token randomness/expiry/single-use, and
revoked-invitation reuse are Better Auth's own, independently
maintained guarantees — not re-implemented here.

## Gate 4 — Tenant-bound database model

One additive Flyway migration, `database/migrations/V10__add_organization_scoping.sql`
(**V1–V9 untouched**):

- Adds `reliability.incidents.organization_id UUID NOT NULL`.
- Backfills every existing row to a fixed, documented constant,
  `00000000-0000-0000-0000-000000000001` ("legacy local-development
  organization") — never "first signup," never a silent production
  fallback.
- Redefines `incidents_active_fingerprint_uniq` to
  `(organization_id, source, source_fingerprint)` (same partial
  predicate), so the exact same dedup semantics now apply per tenant.
- Adds a supporting `(organization_id, last_seen_at DESC)` index.

`remediation_proposals`/`remediation_events` are **not** altered — they
already FK to `incidents.id` and inherit organization scope
transitively via that existing relationship.

Better Auth's own tables (`user`, `session`, `account`, `verification`,
`organization`, `member`, `invitation`) live in a **separate Postgres
schema, `auth`**, owned by a new dedicated, least-privileged role,
`web_console` (`scripts/init-web-console-db.sh`, mirroring
`agent-runtime-service`'s own `agent_runtime` role/schema precedent
exactly). There is **no literal cross-schema foreign key** from
`reliability.incidents.organization_id` to `auth.organization.id` —
Flyway and Better Auth are two independent migration tools with no
guaranteed relative ordering, so referential correctness is enforced
at the **application layer**: control-plane/agent-runtime-service
never need to query the `auth` schema directly at all — the
*web-console BFF* is the only thing that ever reads live membership,
and it passes the already-verified `organization_id` forward inside
the signed assertion.

Better Auth's own schema is applied via a **reviewed, committed SQL
snapshot** (`services/web-console/auth-schema/schema.sql`, generated
once with `npx @better-auth/cli generate` against a real, empty
database — see evidence below) and a small, idempotent bootstrap
script (`scripts/apply-web-console-auth-schema.sh`) — **never**
auto-applied on every container startup.

## Gate 5 — Backend authorization (IDOR protection)

- `control_plane/core/authz.py` / `agent_runtime_service/authz.py`:
  verify the `X-Service-Assertion` header (HS256, pinned issuer/
  audience, bounded clock skew, required claims) and produce an
  `ActorContext {user_id, organization_id, role}` — **only** when
  `CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` is enabled. An absent
  or invalid assertion fails closed (401) whenever enforcement is on.
- Every protected route follows the same four-step pattern: resolve →
  determine tenant → compare → check role — see
  `api/incidents.py::get_incident`, `api/remediation.py::decide_remediation_proposal`,
  `agent_runtime_service/api/agent_runs.py::_require_tenant_access`.
- **No client-supplied organization id is ever trusted.** The actor's
  `organization_id` always comes from the verified assertion; the
  resource's `organization_id` always comes from a fresh database
  read.

## Gate 6 — Internal service trust (status: partially addressed, documented)

Existing machine-to-machine credentials (webhook/lifecycle/remediation
proposal/approver/executor/Kubernetes-ingestion/AWS-ingestion tokens)
are **unchanged** — this phase does not touch them, and does not
require a browser session for any of them. They continue to operate
exactly as before.

**Correction round, Issue 3**: five new, distinct, bounded,
**read-only** internal-service identities were added so that
`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true` does not break any
existing internal read call — see the "Correction round" section
above. None of them is usable as a human-approval credential, and none
grants write access beyond what the pre-existing tokens already
granted.

**Correction round, Issue 4**: `CONTROL_PLANE_ALLOW_LEGACY_INGESTION`
(default `true`) makes the legacy-ingestion boundary an explicit,
operator-visible, testable choice rather than an implicit one — see
the "Correction round" section above.

**What is still NOT implemented** (an honest limitation, not a silent
gap): per-tenant *ingestion* association. Alertmanager/Kubernetes/AWS
findings still land in the one fixed legacy organization regardless of
which real customer environment they came from — Gate 6's "associate
incoming observations with a trusted enrolled integration and
organization" is future work. A global ingestion credential still has
no cross-tenant *read* capability of its own (ingestion is write-only,
and these credentials are never usable for any GET route), so this is
a scoping gap, not a data-exposure one; an operator who wants this
boundary enforced rather than merely documented can now set
`CONTROL_PLANE_ALLOW_LEGACY_INGESTION=false`.

## Gate 7 — Human approval and execution boundary (security-critical)

- `CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN` remains **required**,
  unchanged — this is purely **additive** defense in depth, never a
  replacement.
- When organization-context enforcement is on, `decide_remediation_proposal`
  additionally requires a verified actor whose role is in
  `ROLES_THAT_MAY_DECIDE_REMEDIATION` (`OWNER`, `INCIDENT_APPROVER` —
  **not** `ADMIN`, matching the task's explicit "ADMIN does not
  implicitly bypass remediation approval policy") **and** whose
  organization matches the proposal's owning incident's organization.
  Verified by a real-request test: an `ADMIN` in the correct
  organization still gets 403; an `INCIDENT_APPROVER` in the *wrong*
  organization gets 404 (not 403).
- No new AWS remediation execution; Kubernetes live writes remain
  disabled by default — neither was touched.
- Idempotent/ambiguous-execution behavior in tool-gateway is untouched.

## Gate 8 — Tenant-safe LangGraph runs

- `run_id == thread_id` is preserved exactly as before.
- Every agent-run route (`create`, `get`, `history`, `resume`)
  independently re-derives the run's owning incident's real
  organization from control-plane (never cached, never trusted from
  checkpoint state alone) and compares it to the verified actor —
  `agent_runtime_service/api/agent_runs.py::_require_tenant_access`.
- `VIEWER` cannot create or resume a run, even within their own
  organization (verified test).
- **Not implemented in this phase:** investigator-service/
  retrieval-service's own evidence/runbook reads are not yet
  independently re-scoped by organization — they are reached only
  through agent-runtime-service's own orchestration, which is now
  tenant-checked at the entry point (create/resume), but a
  compromised or buggy agent-runtime-service call into either of
  those two services is not separately defended. Named explicitly as
  deferred, not silently assumed safe.

## Gate 9 — Web-console integration

New screens: `/sign-in`, `/register`, `/organizations` (a single,
consolidated screen covering create/list/switch-active/members/
invitations/accept/reject/revoke/leave — not split into one route per
concern, a deliberate scope simplification), `/unauthorized`. An
`AccountMenu` (role + sign-out) is rendered on every page via the root
layout. Every previously-existing protected route
(`/incidents`, `/incidents/[id]`, `/agent-runs/[id]`, and the three
mutation Route Handlers) now requires a real session and forwards a
freshly-minted service assertion. The UI shows role-appropriate
controls (e.g., only `OWNER`/`ADMIN` see member-management actions),
but — per the task's explicit instruction — this is cosmetic only;
every one of those same actions is independently re-checked and
rejected server-side regardless of what the UI offers.

No landing page, billing, or marketplace work (Phase 15) was done.

## Gate 10 — Security tests (real, not mocked)

**control-plane** (`tests/test_authz.py`, `tests/test_organization_scoping.py`,
24 new tests, run against the real FastAPI app with
`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` explicitly enabled):
missing/forged/wrong-audience/wrong-issuer/expired/unsigned-`alg:none`
assertions rejected; org A cannot list/read/read-events for org B's
incident (404, not 403); same fingerprint in two orgs stays isolated;
VIEWER/ENGINEER/ADMIN cannot decide remediation (403); an
`INCIDENT_APPROVER` in the wrong org cannot decide org A's proposal
(404); the static approver token alone is no longer sufficient; **no
mutation occurs in any rejected case** (asserted directly against the
fake repository's own call-tracking).

**agent-runtime-service** (`tests/test_api_organization_scoping.py`, 9
new tests): VIEWER cannot create a run; ENGINEER cannot create a run
for another org's incident (404); org B cannot read, read history of,
or resume a run created by org A using its real, known run id;
VIEWER cannot resume even their own org's run; missing assertion is
rejected.

**Full regression:** control-plane 340/340 passing (316 pre-existing +
24 new, 23 skipped — pre-existing, Compose-gated), agent-runtime-service
161/161 passing (152 pre-existing + 9 new, 14 skipped — pre-existing,
Compose-gated). Zero pre-existing tests were weakened, removed, or
had their assertions loosened; the only pre-existing-test changes were
adding `organization_id`/new `app.state` fields the fixtures needed to
keep constructing valid objects under the new, additive schema.

**web-console:** `npm run typecheck`, `npm run lint`, and `npm run
build` all pass cleanly (the full route list, including every new
Phase 14 route, compiles).

**Real Better Auth smoke test** (not unit-mocked) against a live,
throwaway `pgvector/pgvector:pg18` container and a live `next dev`
server — see "Validation evidence" below.

**Not run in this session** (named honestly): the existing browser
Playwright E2E suite, the full Docker-Compose-driven CI pipeline
(Alertmanager real-alert-firing, real AWS/Kubernetes observer
scripts), and `detectors`/Phase 10 evals — none of these were touched
by Phase 14's changes, and reproducing the full multi-service Compose
stack was outside this session's practical scope. No claim is made
that they were run.

## Gate 11 — Deployment and safety preparation

- `docker-compose.yml`: `web-console` now depends on `postgres`
  (`service_healthy`) and has five new environment variables
  (`WEB_CONSOLE_DB_USER/PASSWORD`, `BETTER_AUTH_SECRET`,
  `SERVICE_ASSERTION_SIGNING_SECRET`, `WEB_CONSOLE_USE_SECURE_COOKIES`),
  all defaulting to empty/false so `docker compose config` and a clean
  startup still succeed before `make db-up`'s new steps have run.
  `control-plane`/`agent-runtime-service` each gained
  `CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT` (default `false`) and
  `SERVICE_ASSERTION_SIGNING_SECRET`.
- `Makefile`'s `db-up` target now also runs
  `./scripts/init-web-console-db.sh` and
  `./scripts/apply-web-console-auth-schema.sh`, in the same
  credential-before-container-creation order Phase 7 already
  established for `agent-runtime-service`.
- `.env.example` documents every new variable.
- **No infrastructure was provisioned.** No AWS API call, no
  `terraform apply`, no IAM change, no live Kubernetes write, no
  hosted deployment.
- Local developer bootstrap credentials are explicit, generated,
  gitignored `.env` values — never hardcoded, never committed.

## Known limitations (explicit, not silent)

**Superseded by the final rounds above — kept for history, corrected
pointers inline:**

1. ~~No real email delivery.~~ **Still true, but the consequence
   changed**: in secure mode (`CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true`),
   invitation acceptance is now **unavailable entirely** rather than
   falling back to logging a live token — see "BLOCKER 3" above. The
   log-URL fixture remains real, non-faked, and usable, but only in
   local/non-secure deployments.
2. **No MFA/SSO.** Out of scope for this phase.
3. **Ingestion is not yet per-tenant** (Gate 6) — still true, no
   change. Every Alertmanager/Kubernetes/AWS finding lands in one
   fixed legacy organization unless an operator sets
   `CONTROL_PLANE_ALLOW_LEGACY_INGESTION=false` (correction round,
   Issue 4), in which case legacy ingestion is disabled entirely
   rather than a real multi-tenant alternative existing. **Secure
   customer onboarding is NOT complete while this remains true** —
   there is no mechanism anywhere in this platform that associates an
   incoming finding with a specific paying customer's organization.
4. ~~investigator-service and retrieval-service... do NOT
   independently re-verify a human actor's organization~~ — **superseded
   by BLOCKER 1 above**: investigator-service now DOES verify a
   relayed, signed actor assertion from agent-runtime-service (when
   one is sent) before it, in turn, relays a further-derived one to
   control-plane. See "The signing-key boundary, honestly" above for
   the real, precise limit of what this now provides — it is real
   cryptographic verification of a relayed claim, not an independent
   trust domain from agent-runtime-service/control-plane/web-console
   (all four share one symmetric secret).
5. **RLS (Row-Level Security) was not added.** Tenant isolation is
   enforced entirely at the application layer, verified by the tests
   above — RLS was considered as defense-in-depth but not implemented
   in this phase.
6. **The `/organizations` screen is a single consolidated page**, not
   separate routes per the task's literal screen list.
7. ~~Browser E2E... was not re-run~~ — **more precisely, now**: the
   real end-to-end script (`scripts/verify-phase14-multitenant-security.sh`,
   34/34) and the retrieval tenant-isolation script
   (`scripts/verify-retrieval-tenant-isolation.sh`, 15/15) ARE real,
   HTTP-driven, real-process/real-database integration tests, run and
   passing. The actual Playwright BROWSER suite
   (`services/web-console/e2e/phase9-workflow.spec.ts`) is a real,
   pre-existing Phase 9 spec requiring the full live docker-compose
   stack and several real minutes of sustained traffic — it was still
   NOT run in any Phase 14 round, including this one; see "HTTP-based
   real-service checks vs. actual browser-driven E2E" above. Phase 10
   evals (`make eval-offline`), the catalog suite (`make
   catalog-validate`), and the detectors suite (`make
   detectors-validate`) WERE run in the final validation round — Phase
   10's own fixtures had gone stale against Phase 14's new required
   `organization_id` field (a real regression, fixed: see the final
   validation round's report for exact files).
8. No production hosting, HTTPS/reverse-proxy, or external secret
   rotation mechanism is provided — documented as required but
   unimplemented infrastructure, never claimed to exist. This also
   means there is currently no TLS between internal services
   (web-console/control-plane/agent-runtime-service/investigator-service
   all talk to each other over plain HTTP on the Compose-internal
   network) — relevant to the signed-assertion replay-exposure note
   above, since TLS would be what actually closes that gap in a real
   deployment, not a change to the assertion design itself.
9. **The shared symmetric signing secret is one trust perimeter, not
   four independent identities** — see "The signing-key boundary,
   honestly" above. This is the most important limitation in this
   entire document and the one most likely to be glossed over by a
   future reader skimming only the trust-boundary diagram.

## Validation evidence (this session)

- `npx @better-auth/cli generate` against a live, empty
  `pgvector/pgvector:pg18` container produced the real
  `auth-schema/schema.sql` committed here; `npx @better-auth/cli
  migrate` applied it cleanly.
- A real `next dev` server against that same database:
  `POST /api/auth/sign-up/email` → real user created;
  `POST /api/auth/sign-in/email` **without** an `Origin` header →
  rejected (`MISSING_OR_NULL_ORIGIN`); **with** the trusted origin →
  succeeded; `POST /api/auth/organization/create` from an untrusted
  `Origin: http://evil.example.com` → rejected (`INVALID_ORIGIN`);
  the creator's membership row was created with `role: "OWNER"`
  automatically; `GET /api/auth/organization/get-active-member` with a
  forged session cookie → `null` (rejected); with no cookie at all →
  `401 UNAUTHORIZED`; inviting a second member created a real,
  persisted `pending` invitation.
- A real, throwaway Flyway run applied V1–V10 to a fresh database
  (clean pass), and separately V1–V9 first, then one pre-existing
  "legacy" incident row inserted by hand, then V10 — the row's id,
  title, and status were preserved exactly, with `organization_id`
  correctly backfilled to the fixed legacy constant; the redefined
  partial unique index was then proven against a real
  `INSERT ... ON CONFLICT` matching the application's own updated
  upsert statement.
- `scripts/apply-web-console-auth-schema.sh`'s actual SQL pipeline was
  run against a real Postgres role/schema pair, producing all seven
  Better Auth tables inside the dedicated `auth` schema, owned by
  `web_console`, with zero tables appearing in `public` or
  `reliability`.

### Correction round validation (this session)

- Re-ran `npx @better-auth/cli generate` with `generateId: "uuid"`
  active against a live database: confirmed every Better Auth id
  column, including `organization.id`, is now a native Postgres
  `uuid default gen_random_uuid()` column.
- `scripts/verify-phase14-multitenant-security.sh` — a real,
  disposable, end-to-end run (throwaway Postgres with
  `FLYWAY_SCHEMAS=reliability` matching `docker-compose.yml`'s real
  Flyway configuration, a real Better Auth instance, a real
  control-plane instance in secure mode): **23/23 checks passed**,
  covering real-UUID identity creation, cross-tenant incident/
  remediation-proposal access and rejection, no-mutation-on-rejection,
  and all eight invitation-security scenarios from Issue 5. Also
  caught and fixed a real bug along the way (see Issue 1): an untyped
  SQLAlchemy column caused a real `operator does not exist: uuid =
  character varying` error on `GET /api/v1/incidents` under secure
  mode, invisible to the existing mocked-repository tests.
- Full regression after every correction-round change: control-plane
  352 passed/23 skipped; agent-runtime-service 161 passed/14 skipped;
  investigator-service 173 passed; retrieval-service 66 passed/7
  skipped; tool-gateway (`go build`/`go vet`/`go test`) all green,
  `gofmt` clean; web-console `typecheck`/`lint`/`build` all clean. The
  skipped tests in every case are the SAME pre-existing, real-database-
  gated tests (unrelated to this phase) that were already skipped
  before Phase 14 began — none were newly skipped or removed.
- A second real-database check specifically for Issue 2's retrieval
  scoping: seeded two incidents (different organizations) with
  matching `historical_incident` chunks plus one global `knowledge`
  chunk in a real `pgvector` database, and confirmed
  `retrieval_service.db.search_chunks`'s new `organization_id`
  parameter returns only the matching organization's historical chunk
  while leaving the global knowledge chunk visible to both.
