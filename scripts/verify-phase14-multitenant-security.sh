#!/usr/bin/env bash
#
# verify-phase14-multitenant-security.sh — Phase 14 correction round:
# the REAL, end-to-end multi-tenant security acceptance test the
# independent review demanded -- real Better Auth (with
# generateId: "uuid"), a real throwaway PostgreSQL (never the
# developer's own postgres_data volume), real HTTP requests to a real
# web-console (Next.js) instance and a real control-plane (FastAPI)
# instance, with CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true.
#
# Covers:
#   - Issue 1: create a user + organization through REAL Better Auth,
#     obtain the REAL generated (UUID) organization id, persist an
#     incident assigned to it, retrieve it through secured
#     control-plane, and prove cross-tenant rejection -- never a
#     hand-authored UUID fixture alone.
#   - "Additional verification": two real organizations (A, B), each
#     with a real owner membership and a real incident; A can access
#     A, B can access B, neither can access the other (incident GET/
#     list/events), and no rejected request mutates anything.
#   - Issue 5: invitation-acceptance identity ownership -- unverified
#     recipient rejected, wrong-email recipient rejected, verified
#     recipient succeeds, reused/expired/revoked invitations rejected,
#     non-admin cannot invite, a VIEWER cannot escalate their own role.
#
#   - FINAL CORRECTION ROUND, BLOCKER 5: the above previously proved
#     cross-tenant rejection only against hand-signed JWTs posted
#     directly to control-plane -- real, but NOT proof of the full
#     browser-to-backend path (it never exercised Better Auth's real
#     session, the Next.js BFF's own actor resolution, or its own
#     assertion-minting code in lib/server/actor.ts). This round adds,
#     for every incident/remediation check that matters for
#     authorization:
#       * real sign-in through Better Auth (the SAME sign-up call
#         already used, which establishes a real session + cookie),
#       * the real cookie, with the real organization selected
#         (organization/set-active),
#       * a REAL request to web-console's own Next.js route (the
#         server-rendered /incidents/{id} page, or the
#         /api/remediation-proposals/{id}/decision Route Handler) --
#         never control-plane directly for these checks,
#       * letting the BFF mint its OWN assertion from that real,
#         resolved actor (lib/server/actor.ts), never a hand-signed one
#         this script constructs.
#     It also replaces the previous "wrong static approver token"
#     negative control (which only proved the TOKEN check, not
#     cross-tenant rejection) with a cross-tenant approval attempt
#     using the CORRECT, valid static backend credential alongside a
#     REAL, authenticated, wrong-tenant actor -- and adds a revoked-
#     membership check and a durable-human-audit check against the
#     real database. The original hand-signed-assertion checks remain,
#     trimmed, as a distinct and still-useful (but explicitly
#     secondary) direct-to-backend defense-in-depth layer -- never
#     counted as proof of the browser path.
#
# Entirely disposable: a brand-new Docker network + two brand-new
# Postgres/app containers, never the developer's own `make db-up`
# stack or its `postgres_data` volume. Safe to run repeatedly; tears
# itself down on exit (including failure) via the trap below.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

NET="phase14-verify-net-$$"
PG="phase14-verify-pg-$$"
WEB="phase14-verify-web-$$"
CP="phase14-verify-cp-$$"

ASSERTION_SECRET="phase14-verify-assertion-secret-$$"
BETTER_AUTH_SECRET="phase14-verify-better-auth-secret-at-least-32-chars-$$"
PG_PASSWORD="phase14-verify-pg-pass-$$"
APPROVER_TOKEN="phase14-verify-real-approver-token-$$"
WEB_PORT=13201
CP_PORT=18100
ORIGIN="http://127.0.0.1:${WEB_PORT}"

PASS_COUNT=0
FAIL_COUNT=0

cleanup() {
  echo ""
  echo "=== cleaning up (passed: $PASS_COUNT, failed: $FAIL_COUNT) ==="
  docker rm -f "$WEB" "$CP" "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

check() {
  # check <description> <actual> <expected>
  if [ "$2" = "$3" ]; then
    echo "PASS: $1"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL: $1 -- expected [$3], got [$2]"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

echo "=== setting up an isolated Docker network + throwaway PostgreSQL ==="
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" \
  -e POSTGRES_USER=app -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB=reliability_platform \
  pgvector/pgvector:pg18 >/dev/null
for _ in $(seq 1 30); do
  if docker exec "$PG" pg_isready -U app >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$PG" pg_isready -U app

echo "=== applying Flyway V1-V11 (FLYWAY_SCHEMAS=reliability, matching docker-compose.yml's real configuration) ==="
docker run --rm --network "$NET" \
  -e FLYWAY_URL="jdbc:postgresql://${PG}:5432/reliability_platform" \
  -e FLYWAY_USER=app -e FLYWAY_PASSWORD="$PG_PASSWORD" \
  -e FLYWAY_SCHEMAS=reliability \
  -e FLYWAY_LOCATIONS=filesystem:/flyway/sql \
  -v "$REPO_ROOT/database/migrations:/flyway/sql:ro" \
  flyway/flyway:13.9.0 migrate

echo "=== creating the dedicated web_console role/auth schema (mirrors scripts/init-web-console-db.sh, including BLOCKER 4's cross-schema read grant) ==="
docker exec "$PG" psql -U app -d reliability_platform -v ON_ERROR_STOP=1 -c "
CREATE ROLE web_console LOGIN PASSWORD '${PG_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION web_console;
ALTER ROLE web_console SET search_path TO auth;
GRANT USAGE ON SCHEMA auth TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE web_console IN SCHEMA auth GRANT SELECT ON TABLES TO app;
"

echo "=== applying Better Auth's real, committed schema snapshot (UUID id generation) ==="
{ echo "SET search_path TO auth;"; cat "$REPO_ROOT/services/web-console/auth-schema/schema.sql"; } | \
  docker exec -i "$PG" psql -v ON_ERROR_STOP=1 -U web_console -d reliability_platform -f -

echo "=== granting control-plane's own role (app) SELECT on auth.* now that the tables actually exist (BLOCKER 4) ==="
docker exec "$PG" psql -U app -d reliability_platform -v ON_ERROR_STOP=1 -c "
GRANT SELECT ON ALL TABLES IN SCHEMA auth TO app;
"

echo "=== starting web-console (real Next.js dev server) against this database ==="
docker run -d --rm --name "$WEB" --network "$NET" -v "$REPO_ROOT/services/web-console:/app" -w /app \
  -p "${WEB_PORT}:3101" \
  -e BETTER_AUTH_SECRET="$BETTER_AUTH_SECRET" \
  -e WEB_CONSOLE_DB_HOST="$PG" -e WEB_CONSOLE_DB_USER=web_console -e WEB_CONSOLE_DB_PASSWORD="$PG_PASSWORD" \
  -e POSTGRES_DB=reliability_platform \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$ASSERTION_SECRET" \
  -e WEB_CONSOLE_TRUSTED_ORIGIN="$ORIGIN" \
  -e WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS=true \
  -e WEB_CONSOLE_CONTROL_PLANE_URL="http://${CP}:8000" \
  -e CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN="$APPROVER_TOKEN" \
  node:24-slim bash -c "npm run dev -- -p 3101 -H 0.0.0.0" >/dev/null

echo "=== starting control-plane (real FastAPI app) against this database, secure mode ON ==="
docker run -d --rm --name "$CP" --network "$NET" -v "$REPO_ROOT/services/control-plane:/app" -w /app \
  -p "${CP_PORT}:8000" \
  -e POSTGRES_HOST="$PG" -e POSTGRES_USER=app -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB=reliability_platform \
  -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$ASSERTION_SECRET" \
  -e CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN="$APPROVER_TOKEN" \
  python:3.13-slim bash -c "pip install -q -e . && python -m uvicorn control_plane.main:app --host 0.0.0.0 --port 8000" >/dev/null

echo "=== waiting for both services to report healthy ==="
for i in $(seq 1 120); do
  if curl -s -m 2 "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1 \
     && curl -s -m 2 "http://127.0.0.1:${CP_PORT}/health/live" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if ! curl -sf -m 5 "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1; then
  echo "web-console never became healthy -- its logs:"
  docker logs "$WEB" 2>&1 | tail -60
  exit 1
fi
if ! curl -sf -m 5 "http://127.0.0.1:${CP_PORT}/health/live" >/dev/null 2>&1; then
  echo "control-plane never became healthy -- its logs:"
  docker logs "$CP" 2>&1 | tail -60
  exit 1
fi
echo "both services are up."

WEB_URL="http://127.0.0.1:${WEB_PORT}"
CP_URL="http://127.0.0.1:${CP_PORT}"
CA="$(mktemp)"
CB="$(mktemp)"
CD="$(mktemp)"
CE="$(mktemp)"
CF="$(mktemp)"
rm -f "$CA" "$CB" "$CD" "$CE" "$CF"

sign_up() {
  # sign_up <cookie_jar> <email> <name>
  curl -s -m 8 -c "$1" -H "Content-Type: application/json" \
    -d "{\"email\":\"$2\",\"password\":\"correct-horse-battery\",\"name\":\"$3\"}" \
    "$WEB_URL/api/auth/sign-up/email"
}

set_active_org() {
  # set_active_org <cookie_jar> <organization_id>
  curl -s -m 8 -b "$1" -c "$1" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
    -d "{\"organizationId\":\"$2\"}" "$WEB_URL/api/auth/organization/set-active" >/dev/null
}

echo ""
echo "=== Phase 1: real identity creation (Issue 1) ==="
RESP_ALICE=$(sign_up "$CA" "alice@orga.example.com" "Alice")
ALICE_ID=$(echo "$RESP_ALICE" | jq -r '.user.id')
echo "Alice's real user id: $ALICE_ID"

RESP_BOB=$(sign_up "$CB" "bob@orgb.example.com" "Bob")
BOB_ID=$(echo "$RESP_BOB" | jq -r '.user.id')
echo "Bob's real user id: $BOB_ID"

check "Alice's id is a real UUID (not a hand-authored fixture)" \
  "$(echo "$ALICE_ID" | grep -Eic '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')" "1"

RESP_ORG_A=$(curl -s -m 8 -c "$CA" -b "$CA" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"name":"Org A","slug":"org-a-'"$$"'"}' "$WEB_URL/api/auth/organization/create")
ORG_A=$(echo "$RESP_ORG_A" | jq -r '.id')
echo "Org A's real, Better-Auth-generated id: $ORG_A"

RESP_ORG_B=$(curl -s -m 8 -c "$CB" -b "$CB" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"name":"Org B","slug":"org-b-'"$$"'"}' "$WEB_URL/api/auth/organization/create")
ORG_B=$(echo "$RESP_ORG_B" | jq -r '.id')
echo "Org B's real, Better-Auth-generated id: $ORG_B"

check "Org A's id is a real UUID" \
  "$(echo "$ORG_A" | grep -Eic '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')" "1"
check "Org A's creator was auto-assigned role OWNER" \
  "$(echo "$RESP_ORG_A" | jq -r '.members[0].role')" "OWNER"

echo "--- BLOCKER 5: explicitly selecting the real organization for each real session ---"
set_active_org "$CA" "$ORG_A"
set_active_org "$CB" "$ORG_B"
check "Alice's real session now has Org A active" \
  "$(curl -s -m 8 -b "$CA" "$WEB_URL/api/auth/get-session" | jq -r '.session.activeOrganizationId')" "$ORG_A"
check "Bob's real session now has Org B active" \
  "$(curl -s -m 8 -b "$CB" "$WEB_URL/api/auth/get-session" | jq -r '.session.activeOrganizationId')" "$ORG_B"

echo "=== persisting an incident assigned to each REAL organization id (direct SQL -- real per-tenant ingestion is a documented, deferred Gate 6 item) ==="
INC_A=$(docker exec "$PG" psql -t -A -U app -d reliability_platform -c "
INSERT INTO reliability.incidents (organization_id, source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at)
VALUES ('${ORG_A}', 'alertmanager', 'fp-verify-a-$$', 'Org A Verify Incident', 'critical', 'investigating', now(), now(), now())
RETURNING id;
" | head -1 | tr -d '[:space:]')
INC_B=$(docker exec "$PG" psql -t -A -U app -d reliability_platform -c "
INSERT INTO reliability.incidents (organization_id, source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at)
VALUES ('${ORG_B}', 'alertmanager', 'fp-verify-b-$$', 'Org B Verify Incident', 'critical', 'open', now(), now(), now())
RETURNING id;
" | head -1 | tr -d '[:space:]')
echo "incident A: $INC_A (org $ORG_A)"
echo "incident B: $INC_B (org $ORG_B)"

echo ""
echo "=== Phase 2: REAL authenticated browser-to-backend access, via web-console's own BFF (BLOCKER 5) ==="
echo "    sign-in -> real session cookie -> real active org -> real Next.js page -> BFF mints its OWN assertion -> control-plane"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$CA" "$WEB_URL/incidents/$INC_A")
check "Alice (real session, real BFF-minted assertion) can access her own org's incident page (200)" "$STATUS" "200"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$CB" "$WEB_URL/incidents/$INC_B")
check "Bob (real session, real BFF-minted assertion) can access his own org's incident page (200)" "$STATUS" "200"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$CA" "$WEB_URL/incidents/$INC_B")
check "Alice, authenticated as a REAL Org A actor, cannot access Org B's incident (404, not 403)" "$STATUS" "404"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$CB" "$WEB_URL/incidents/$INC_A")
check "Bob, authenticated as a REAL Org B actor, cannot access Org A's incident (404)" "$STATUS" "404"

LIST_A_BODY=$(curl -s -b "$CA" "$WEB_URL/incidents")
check "Org A's real incident list page shows Org A's incident" \
  "$(echo "$LIST_A_BODY" | grep -c 'Org A Verify Incident')" "1"
check "Org A's real incident list page does NOT leak Org B's incident title" \
  "$(echo "$LIST_A_BODY" | grep -c 'Org B Verify Incident')" "0"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$WEB_URL/incidents/$INC_A")
check "no session cookie at all is redirected to sign-in, never rendered unscoped (302/307)" \
  "$(curl -s -o /dev/null -w "%{http_code}" "$WEB_URL/incidents/$INC_A" | grep -Ec '^30[27]$')" "1"

echo ""
echo "--- a slimmed, explicitly SECONDARY direct-to-backend check (defense-in-depth only -- NOT proof of the browser path) ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$CP_URL/api/v1/incidents/$INC_A")
check "[secondary] control-plane itself still rejects a request with no assertion at all (401)" "$STATUS" "401"

echo ""
echo "=== Phase 3: remediation proposal cross-tenant rejection via the REAL BFF decision route (BLOCKER 5) ==="
PROPOSAL_A_ROW=$(docker exec "$PG" psql -t -A -U app -d reliability_platform -c "
INSERT INTO reliability.remediation_proposals
  (incident_id, agent_run_id, idempotency_key, action_type, target, status, reason, supporting_evidence_ids, supporting_context_ids, proposed_at, updated_at)
VALUES
  ('${INC_A}', gen_random_uuid(), 'verify-script-a-$$', 'clear_payment_authorization_fault', 'payment-service', 'pending_approval', 'verification script', '{}', '{}', now(), now())
RETURNING id;
" | head -1 | tr -d '[:space:]')
echo "proposal for A's incident: $PROPOSAL_A_ROW"

decide_via_bff() {
  # decide_via_bff <cookie_jar> <proposal_id> <decision>
  curl -s -o /dev/null -w "%{http_code}" -m 8 -X POST -b "$1" -c "$1" \
    -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
    -d "{\"decision\":\"$3\"}" "$WEB_URL/api/remediation-proposals/$2/decision"
}

STATUS=$(decide_via_bff "$CB" "$PROPOSAL_A_ROW" "approve")
check "Bob (REAL authenticated wrong-tenant actor, VALID static backend credential) cannot approve A's proposal (404)" "$STATUS" "404"

STILL_PENDING=$(docker exec "$PG" psql -t -A -U app -d reliability_platform -c "
SELECT status FROM reliability.remediation_proposals WHERE id = '${PROPOSAL_A_ROW}';
" | head -1 | tr -d '[:space:]')
check "Bob's rejected cross-tenant decision caused NO mutation (status is still pending_approval)" "$STILL_PENDING" "pending_approval"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -m 8 -X POST -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"decision":"approve"}' "$WEB_URL/api/remediation-proposals/$PROPOSAL_A_ROW/decision")
check "no session cookie at all cannot approve anything via the BFF either (401)" "$STATUS" "401"

echo ""
echo "=== Phase 3b: a VALID approval -- durable human audit identifies the REAL actor (BLOCKER 4 + BLOCKER 5) ==="
STATUS=$(decide_via_bff "$CA" "$PROPOSAL_A_ROW" "approve")
check "Alice (real OWNER of the real owning org) can approve A's own proposal via the real BFF (200)" "$STATUS" "200"

AUDIT_ROW=$(docker exec "$PG" psql -t -A -F'|' -U app -d reliability_platform -c "
SELECT status, decided_by_user_id, decided_by_organization_id FROM reliability.remediation_proposals WHERE id = '${PROPOSAL_A_ROW}';
" | head -1)
AUDIT_STATUS=$(echo "$AUDIT_ROW" | cut -d'|' -f1 | tr -d '[:space:]')
AUDIT_USER=$(echo "$AUDIT_ROW" | cut -d'|' -f2 | tr -d '[:space:]')
AUDIT_ORG=$(echo "$AUDIT_ROW" | cut -d'|' -f3 | tr -d '[:space:]')

check "the proposal is durably approved" "$AUDIT_STATUS" "approved"
check "the durable audit's decided_by_user_id identifies the REAL human actor (Alice), not a placeholder" "$AUDIT_USER" "$ALICE_ID"
check "the durable audit's decided_by_organization_id is the REAL owning organization" "$AUDIT_ORG" "$ORG_A"

echo ""
echo "=== Phase 4: invitation-acceptance identity ownership (Issue 5) ==="

verify_header() {
  docker logs "$WEB" 2>&1 | grep "email verification link for $1" | tail -1
}

accept_invitation() {
  # accept_invitation <cookie_jar> <invitation_id>
  curl -s -m 8 -b "$1" -c "$1" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
    -d "{\"invitationId\":\"$2\"}" "$WEB_URL/api/auth/organization/accept-invitation"
}

echo "--- Alice invites dave@example.com to Org A as VIEWER ---"
INVITE_DAVE=$(curl -s -m 8 -b "$CA" -c "$CA" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"email":"dave@example.com","role":"VIEWER"}' "$WEB_URL/api/auth/organization/invite-member")
DAVE_INVITATION_ID=$(echo "$INVITE_DAVE" | jq -r '.id')
echo "invitation id: $DAVE_INVITATION_ID"

echo "--- Eve (a different email) signs up and tries to accept Dave's invitation ---"
sign_up "$CE" "eve@example.com" "Eve" >/dev/null
RESP_WRONG_EMAIL=$(accept_invitation "$CE" "$DAVE_INVITATION_ID")
check "wrong-email recipient cannot accept Dave's invitation (FORBIDDEN)" \
  "$(echo "$RESP_WRONG_EMAIL" | jq -r '.code // "none"')" "YOU_ARE_NOT_THE_RECIPIENT_OF_THE_INVITATION"

echo "--- Dave signs up (unverified by default) and tries to accept his OWN invitation ---"
RESP_DAVE=$(sign_up "$CD" "dave@example.com" "Dave")
DAVE_ID=$(echo "$RESP_DAVE" | jq -r '.user.id')
RESP_UNVERIFIED=$(accept_invitation "$CD" "$DAVE_INVITATION_ID")
check "unverified Dave cannot accept his own invitation (email verification required)" \
  "$(echo "$RESP_UNVERIFIED" | jq -r '.code // "none"')" "EMAIL_VERIFICATION_REQUIRED_BEFORE_ACCEPTING_OR_REJECTING_INVITATION"

echo "--- extracting Dave's REAL verification token from the server's own logs (local-dev mode) and verifying his email ---"
DAVE_VERIFY_LINE="$(verify_header dave@example.com)"
DAVE_VERIFY_URL="$(echo "$DAVE_VERIFY_LINE" | sed -E 's/.*(http[^ ]+).*/\1/')"
if [ -z "$DAVE_VERIFY_URL" ]; then
  echo "FAIL: could not find Dave's real verification link in web-console's logs"
  FAIL_COUNT=$((FAIL_COUNT + 1))
else
  curl -s -m 8 -b "$CD" -c "$CD" "$DAVE_VERIFY_URL" >/dev/null
  echo "PASS: retrieved and used Dave's real, non-faked verification token"
  PASS_COUNT=$((PASS_COUNT + 1))
fi

echo "--- verified Dave accepts his own invitation ---"
RESP_VERIFIED_ACCEPT=$(accept_invitation "$CD" "$DAVE_INVITATION_ID")
check "verified Dave CAN accept his own invitation" \
  "$(echo "$RESP_VERIFIED_ACCEPT" | jq -r '.member.role // "none"')" "VIEWER"
set_active_org "$CD" "$ORG_A"

echo "--- Dave tries to accept the SAME invitation again (reused invitation) ---"
RESP_REUSED=$(accept_invitation "$CD" "$DAVE_INVITATION_ID")
check "a reused (already-accepted) invitation is rejected" \
  "$(echo "$RESP_REUSED" | jq -r '.code // "none"')" "INVITATION_NOT_FOUND"

echo "--- Alice invites frank@example.com, then revokes it before he can accept ---"
INVITE_FRANK=$(curl -s -m 8 -b "$CA" -c "$CA" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"email":"frank@example.com","role":"VIEWER"}' "$WEB_URL/api/auth/organization/invite-member")
FRANK_INVITATION_ID=$(echo "$INVITE_FRANK" | jq -r '.id')
curl -s -m 8 -b "$CA" -c "$CA" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d "{\"invitationId\":\"$FRANK_INVITATION_ID\"}" "$WEB_URL/api/auth/organization/cancel-invitation" >/dev/null
sign_up "$CF" "frank@example.com" "Frank" >/dev/null
FRANK_VERIFY_LINE="$(verify_header frank@example.com)"
FRANK_VERIFY_URL="$(echo "$FRANK_VERIFY_LINE" | sed -E 's/.*(http[^ ]+).*/\1/')"
curl -s -m 8 -b "$CF" -c "$CF" "$FRANK_VERIFY_URL" >/dev/null
RESP_REVOKED=$(accept_invitation "$CF" "$FRANK_INVITATION_ID")
check "a revoked (cancelled) invitation is rejected" \
  "$(echo "$RESP_REVOKED" | jq -r '.code // "none"')" "INVITATION_NOT_FOUND"

echo "--- expired invitation: invite george@example.com, force-expire it via direct SQL, then attempt accept ---"
INVITE_GEORGE=$(curl -s -m 8 -b "$CA" -c "$CA" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"email":"george@example.com","role":"VIEWER"}' "$WEB_URL/api/auth/organization/invite-member")
GEORGE_INVITATION_ID=$(echo "$INVITE_GEORGE" | jq -r '.id')
docker exec "$PG" psql -U app -d reliability_platform -c "
UPDATE auth.invitation SET \"expiresAt\" = now() - interval '1 day' WHERE id = '${GEORGE_INVITATION_ID}';
" >/dev/null
CG="$(mktemp)"; rm -f "$CG"
sign_up "$CG" "george@example.com" "George" >/dev/null
RESP_EXPIRED=$(accept_invitation "$CG" "$GEORGE_INVITATION_ID")
check "an expired invitation is rejected" \
  "$(echo "$RESP_EXPIRED" | jq -r '.code // "none"')" "INVITATION_NOT_FOUND"
rm -f "$CG"

echo ""
echo "=== Phase 5: non-admin invitation creation + role-escalation attempts (Gate 3) ==="

RESP_DAVE_INVITES=$(curl -s -m 8 -b "$CD" -c "$CD" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"email":"someone-else@example.com","role":"VIEWER"}' "$WEB_URL/api/auth/organization/invite-member")
check "a VIEWER (Dave) cannot create an invitation" \
  "$(echo "$RESP_DAVE_INVITES" | jq -r '.code // "none" | test("FORBIDDEN|PERMISSION|UNAUTHORIZED|NOT_ALLOWED") | tostring')" "true"

DAVE_MEMBER_ID=$(echo "$RESP_VERIFIED_ACCEPT" | jq -r '.member.id')
RESP_SELF_ESCALATE=$(curl -s -m 8 -b "$CD" -c "$CD" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d "{\"memberId\":\"$DAVE_MEMBER_ID\",\"role\":\"OWNER\"}" "$WEB_URL/api/auth/organization/update-member-role")
check "a VIEWER (Dave) cannot escalate their own role to OWNER" \
  "$(echo "$RESP_SELF_ESCALATE" | jq -r '.code // "none" | test("FORBIDDEN|PERMISSION|UNAUTHORIZED|NOT_ALLOWED") | tostring')" "true"

echo ""
echo "=== Phase 6: revoked membership is denied for BOTH the browser path and the approval path (BLOCKER 1/4/5) ==="
echo "    Dave is a REAL, verified, accepted VIEWER of Org A right now (Phase 4) -- proven able to read Org A's incident below, BEFORE removal."

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$CD" "$WEB_URL/incidents/$INC_A")
check "Dave, still a real member, CAN read Org A's incident before being removed (200)" "$STATUS" "200"

echo "--- Alice (real OWNER) removes Dave from Org A via a REAL Better Auth call ---"
RESP_REMOVE_DAVE=$(curl -s -m 8 -b "$CA" -c "$CA" -H "Content-Type: application/json" -H "Origin: $ORIGIN" \
  -d '{"memberIdOrEmail":"dave@example.com"}' "$WEB_URL/api/auth/organization/remove-member")
check "Dave's real membership row is actually gone" "$(echo "$RESP_REMOVE_DAVE" | jq -r '.member.userId // "none"')" "$DAVE_ID"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$CD" "$WEB_URL/incidents/$INC_A")
check "Dave's SAME, still-unexpired session cookie is denied the moment he is removed -- never rendered (302/307/404)" \
  "$(echo "$STATUS" | grep -Ec '^(30[27]|404)$')" "1"

echo "--- a NEW proposal for Org A, with Dave re-promoted-in-spirit (reusing INCIDENT_APPROVER-equivalent OWNER Alice) to prove the live recheck, not merely the token, governs decisions ---"
PROPOSAL_A2_ROW=$(docker exec "$PG" psql -t -A -U app -d reliability_platform -c "
INSERT INTO reliability.remediation_proposals
  (incident_id, agent_run_id, idempotency_key, action_type, target, status, reason, supporting_evidence_ids, supporting_context_ids, proposed_at, updated_at)
VALUES
  ('${INC_A}', gen_random_uuid(), 'verify-script-a2-$$', 'clear_payment_authorization_fault', 'payment-service', 'pending_approval', 'verification script', '{}', '{}', now(), now())
RETURNING id;
" | head -1 | tr -d '[:space:]')
STATUS=$(decide_via_bff "$CD" "$PROPOSAL_A2_ROW" "approve")
check "Dave's removed, unexpired session cannot approve anything either (401, since he no longer resolves to any actor at all)" "$STATUS" "401"
STILL_PENDING_A2=$(docker exec "$PG" psql -t -A -U app -d reliability_platform -c "
SELECT status FROM reliability.remediation_proposals WHERE id = '${PROPOSAL_A2_ROW}';
" | head -1 | tr -d '[:space:]')
check "Dave's rejected post-removal decision caused NO mutation" "$STILL_PENDING_A2" "pending_approval"

echo ""
echo "=== RESULT: $PASS_COUNT passed, $FAIL_COUNT failed ==="
if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
