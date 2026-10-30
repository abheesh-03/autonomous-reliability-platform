#!/usr/bin/env bash
#
# test-restore-live-login-proof.sh -- Phase 17A correction round, item 4.
#
# Real proof that a database restored by deploy/scripts/restore.sh
# can actually be used by the REAL application -- not merely that its
# tables/roles exist by direct SQL introspection (which is additional
# evidence, never a substitute). Builds real web-console and
# control-plane images from their real Dockerfiles, runs them against
# a real SOURCE database, creates a real user/organization/incident
# through them, backs up and restores that database into a brand-new
# disposable TARGET, runs NEW web-console/control-plane containers
# against the TARGET with restore.sh's own newly-generated
# credentials, and proves the SAME real user can sign in there and
# read back the SAME tenant-scoped data.
#
# Everything here is disposable and uniquely named (PID+timestamp) --
# never the developer's own dev stack/db/volumes/images.
#
# CORRECTION ROUND (second pass): previously ran with
# CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT unset (local-dev auth
# mode) throughout, and its final incidents-read proof hit
# control-plane directly over HTTP with no Authorization/assertion
# header at all -- it proved the restored DATA was intact and
# correctly tagged, but never that the real, enforced,
# authenticated-tenant-scoped READ boundary itself still holds after
# a restore. Fixed: runs with CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true
# on every application container (both the SOURCE and the RESTORED
# TARGET), which (lib/auth/deployment-mode.ts's isSecureDeployment())
# forces real SMTP delivery instead of the log fallback -- a
# disposable mailpit (the same pattern deploy/scripts/
# test-cross-tenant-and-revocation-proof.sh already uses) stands in
# for a real receiver. The final read goes through web-console's own
# real, authenticated `/incidents` page (requireActorOrRedirect() +
# signAssertion(), the exact same server-side path a real signed-in
# browser session uses -- see app/incidents/page.tsx) using the real
# session cookie from this script's own sign-in, instead of a raw,
# unauthenticated curl to control-plane. A companion check confirms
# enforcement is genuinely active, not merely configured: the SAME
# unauthenticated direct request to control-plane now gets a real 401
# (core/authz.py's get_actor_context raises one whenever
# organization-context enforcement is on and no X-Service-Assertion
# header is present).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"

fail() { echo "FAIL: $1" >&2; exit 1; }
FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

RUN_ID="$$-$(date +%s)"
NETWORK_NAME="arp-restore-login-proof-net-$RUN_ID"
SRC_PG="arp-restore-login-proof-src-pg-$RUN_ID"
TGT_PG="arp-restore-login-proof-tgt-pg-$RUN_ID"
SRC_WC="arp-restore-login-proof-src-wc-$RUN_ID"
SRC_CP="arp-restore-login-proof-src-cp-$RUN_ID"
TGT_WC="arp-restore-login-proof-tgt-wc-$RUN_ID"
TGT_CP="arp-restore-login-proof-tgt-cp-$RUN_ID"
MAILPIT="arp-restore-login-proof-mailpit-$RUN_ID"
WC_IMAGE="arp-restore-login-proof-wc-image-$RUN_ID"
CP_IMAGE="arp-restore-login-proof-cp-image-$RUN_ID"
BOOTSTRAP_PW="bootstrap-$RUN_ID"
BETTER_AUTH_SECRET="auth-secret-$RUN_ID-0123456789abcdef"
SERVICE_ASSERTION_SIGNING_SECRET="svc-secret-$RUN_ID-0123456789abcdef0123456789abcdef"
MAILPIT_API="http://$MAILPIT:8025/api/v1"
BACKUP_DIR="$(mktemp -d)"
CREDS_OUT="$(mktemp -u)"

cleanup() {
  docker rm -f "$SRC_WC" "$SRC_CP" "$TGT_WC" "$TGT_CP" "$SRC_PG" "$TGT_PG" "$MAILPIT" >/dev/null 2>&1 || true
  docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
  docker rmi "$WC_IMAGE" "$CP_IMAGE" >/dev/null 2>&1 || true
  rm -rf "$BACKUP_DIR" "$CREDS_OUT" "${HTTP_DIR:-}"
}
trap cleanup EXIT

wait_pg_ready() {
  local container="$1" pw="$2"
  local ready=0
  for _ in $(seq 1 60); do
    if docker exec -e PGPASSWORD="$pw" "$container" psql -U postgres -d postgres -c "SELECT 1;" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  [ "$ready" -eq 1 ] || fail "$container never became ready"
}

# For a container with no HOST-published port (control-plane here --
# only reachable from other containers on $NETWORK_NAME) -- real
# finding while writing this script: an earlier draft tried to
# `docker port` a container that was never `-p`-published at all,
# which silently failed in a way its own `|| true` guard could not
# actually catch (`fail()` calls `exit`, which no `||` on its own
# call site can intercept).
wait_http_ready_in_network() {
  local url="$1" label="$2"
  local ready=0
  for _ in $(seq 1 60); do
    if docker run --rm --network "$NETWORK_NAME" curlimages/curl:8.11.1 -s -o /dev/null -w '%{http_code}' "$url" 2>/dev/null | grep -qE '^[23]'; then
      ready=1
      break
    fi
    sleep 1
  done
  [ "$ready" -eq 1 ] || fail "$label never became ready at $url"
}

echo "== building real web-console and control-plane images (reused for both source and target) =="
docker build -q -t "$WC_IMAGE" "$REPO_ROOT/services/web-console" >/dev/null
docker build -q -t "$CP_IMAGE" "$REPO_ROOT/services/control-plane" >/dev/null

echo "== starting the disposable SOURCE PostgreSQL instance =="
docker network create "$NETWORK_NAME" >/dev/null
docker run -d --name "$SRC_PG" --network "$NETWORK_NAME" \
  -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=reliability_platform \
  pgvector/pgvector:pg18 >/dev/null
wait_pg_ready "$SRC_PG" "$BOOTSTRAP_PW"

echo "== starting a disposable mailpit (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true forces real SMTP, never the log fallback) =="
docker run -d --name "$MAILPIT" --network "$NETWORK_NAME" axllent/mailpit:v1.20.0 >/dev/null
sleep 2

echo "== applying the REAL Flyway migrations (database/migrations/, unmodified) =="
docker run --rm --network "$NETWORK_NAME" \
  -e FLYWAY_URL="jdbc:postgresql://$SRC_PG:5432/reliability_platform" \
  -e FLYWAY_USER=postgres -e FLYWAY_PASSWORD="$BOOTSTRAP_PW" \
  -e FLYWAY_SCHEMAS=reliability -e FLYWAY_LOCATIONS=filesystem:/flyway/sql \
  -v "$REPO_ROOT/database/migrations:/flyway/sql:ro" \
  flyway/flyway:13.9.0 migrate >/dev/null

echo "== applying the REAL, unmodified runtime-roles template =="
CONTROL_PLANE_APP_PASSWORD="cp-app-$RUN_ID"
RETRIEVAL_APP_PASSWORD="ra-app-$RUN_ID"
WEB_CONSOLE_DB_PASSWORD="wc-app-$RUN_ID"
AGENT_RUNTIME_PASSWORD="ar-app-$RUN_ID"
sed \
  -e "s/CONTROL_PLANE_APP_PASSWORD_PLACEHOLDER/$CONTROL_PLANE_APP_PASSWORD/" \
  -e "s/RETRIEVAL_APP_PASSWORD_PLACEHOLDER/$RETRIEVAL_APP_PASSWORD/" \
  -e "s/WEB_CONSOLE_PASSWORD_PLACEHOLDER/$WEB_CONSOLE_DB_PASSWORD/" \
  -e "s/AGENT_RUNTIME_PASSWORD_PLACEHOLDER/$AGENT_RUNTIME_PASSWORD/" \
  "$DEPLOY_DIR/sql/01-create-runtime-roles.sql.template" \
  | docker exec -i -e PGPASSWORD="$BOOTSTRAP_PW" "$SRC_PG" psql -v ON_ERROR_STOP=1 -U postgres -d reliability_platform -f -

echo "== applying the REAL Better Auth schema.sql, connected as web_console (exactly matches apply-deploy-auth-schema.sh) =="
{ echo "SET search_path TO auth;"; cat "$REPO_ROOT/services/web-console/auth-schema/schema.sql"; } \
  | docker exec -i -e PGPASSWORD="$WEB_CONSOLE_DB_PASSWORD" "$SRC_PG" psql -v ON_ERROR_STOP=1 -U web_console -d reliability_platform -f -

echo "== re-asserting the real, narrowed control_plane_app grant on auth.member (matches apply-deploy-auth-schema.sh) =="
docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$SRC_PG" psql -v ON_ERROR_STOP=1 -U postgres -d reliability_platform \
  -c 'REVOKE SELECT ON ALL TABLES IN SCHEMA auth FROM control_plane_app;' \
  -c 'GRANT SELECT ("organizationId", "userId", "role") ON auth.member TO control_plane_app;' >/dev/null

echo "== starting the SOURCE control-plane (real image, real DB role, organization-context enforcement ON) =="
docker run -d --name "$SRC_CP" --network "$NETWORK_NAME" \
  -e POSTGRES_HOST="$SRC_PG" -e POSTGRES_USER=control_plane_app -e POSTGRES_PASSWORD="$CONTROL_PLANE_APP_PASSWORD" \
  -e POSTGRES_DB=reliability_platform \
  -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$SERVICE_ASSERTION_SIGNING_SECRET" \
  "$CP_IMAGE" >/dev/null

echo "== starting the SOURCE web-console (real image, real DB role, secure-deployment auth mode: real SMTP, enforcement ON) =="
# No published host port at all -- every HTTP call below goes through
# a disposable curl container ON $NETWORK_NAME instead, using the
# SAME container-name:port address as WEB_CONSOLE_TRUSTED_ORIGIN.
# (Real finding from this proof's own earlier run: a host-published
# RANDOM port, e.g. "-p 127.0.0.1:0:3101", gives the HOST a different
# origin than whatever WEB_CONSOLE_TRUSTED_ORIGIN the container itself
# was started with -- Better Auth's own trustedOrigins check then
# correctly rejects the request as a mismatched Origin. Addressing
# everything by the one real container-network origin both sides
# actually agree on removes that mismatch entirely.)
SRC_WC_ORIGIN="http://$SRC_WC:3101"
docker run -d --name "$SRC_WC" --network "$NETWORK_NAME" \
  -e POSTGRES_HOST="$SRC_PG" -e POSTGRES_DB=reliability_platform \
  -e WEB_CONSOLE_DB_USER=web_console -e WEB_CONSOLE_DB_PASSWORD="$WEB_CONSOLE_DB_PASSWORD" \
  -e BETTER_AUTH_SECRET="$BETTER_AUTH_SECRET" \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$SERVICE_ASSERTION_SIGNING_SECRET" \
  -e WEB_CONSOLE_TRUSTED_ORIGIN="$SRC_WC_ORIGIN" \
  -e WEB_CONSOLE_CONTROL_PLANE_URL="http://$SRC_CP:8000" \
  -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
  -e SMTP_HOST="$MAILPIT" -e SMTP_PORT=1025 -e SMTP_FROM_ADDRESS="noreply@restore-proof.test" -e SMTP_SECURITY=none \
  -e ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true \
  "$WC_IMAGE" >/dev/null

wait_http_ready_in_network "http://$SRC_CP:8000/health/live" "source control-plane"
wait_http_ready_in_network "$SRC_WC_ORIGIN/api/health" "source web-console"

# A disposable curl container's own filesystem is lost the instant
# `--rm` removes it -- a HOST-side directory, bind-mounted into every
# invocation below, is what lets a cookie jar/response body actually
# persist across SEPARATE `docker run` calls.
HTTP_DIR="$(mktemp -d)"
curl_net() {
  # $1 = curl's own args/flags; mounts $HTTP_DIR at /http inside the
  # disposable container, so -c/-b/-o paths under /http persist on
  # the host at $HTTP_DIR.
  docker run --rm --network "$NETWORK_NAME" -v "$HTTP_DIR:/http" curlimages/curl:8.11.1 "$@"
}

echo ""
echo "== real sign-up / email verification (log fallback) / sign-in / organization create against SOURCE =="
EMAIL_SUFFIX="$RANDOM$RANDOM"
USER_EMAIL="restore-proof-user-$EMAIL_SUFFIX@example.com"
USER_PASSWORD="CorrectHorseBattery12!"
HEADERS=(-H "Origin: $SRC_WC_ORIGIN" -H "Content-Type: application/json")

signup_status="$(curl_net -s -o /http/signup.json -w '%{http_code}' -c /http/jar.txt "${HEADERS[@]}" \
  -X POST "$SRC_WC_ORIGIN/api/auth/sign-up/email" \
  -d "{\"email\":\"$USER_EMAIL\",\"password\":\"$USER_PASSWORD\",\"name\":\"Restore Proof User\"}")"
[ "$signup_status" = "200" ] || fail "sign-up failed: got $signup_status, body: $(cat "$HTTP_DIR/signup.json" 2>/dev/null)"
case_pass "real sign-up succeeded against SOURCE web-console"

# CORRECTION ROUND (second pass): extracts the real verification
# link from mailpit's own HTTP API now (real SMTP delivery, forced by
# CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true) instead of grepping
# web-console's own log-fallback message, which that mode no longer
# ever prints.
wait_for_mail() {
  # $1 = recipient, $2 = subject substring. Prints the message body on
  # stdout.
  local to="$1" subject="$2"
  for _ in $(seq 1 40); do
    local list_body
    list_body="$(curl_net -s "$MAILPIT_API/messages?limit=50")"
    local msg_id
    msg_id="$(echo "$list_body" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for m in data.get('messages', []):
    to_list = [t.get('Address', '') for t in m.get('To', [])]
    if '$to' in to_list and '$subject'.lower() in m.get('Subject', '').lower():
        print(m['ID'])
        break
" 2>/dev/null)"
    if [ -n "$msg_id" ]; then
      curl_net -s "$MAILPIT_API/message/$msg_id" | python3 -c "import json,sys; print(json.load(sys.stdin).get('Text',''))"
      return 0
    fi
    sleep 1
  done
  return 1
}

verify_msg="$(wait_for_mail "$USER_EMAIL" "verify")" || fail "no real verification email arrived at mailpit for $USER_EMAIL"
verify_url="$(echo "$verify_msg" | grep -oE "https?://\S+" | head -1 | sed -E 's/[.,]+$//')"
[ -n "$verify_url" ] || fail "verification email arrived but contained no real link"
case_pass "found the real verification link via mailpit's own HTTP API (real SMTP delivery, not the log fallback)"

verify_status="$(curl_net -s -o /dev/null -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt "$verify_url")"
[ "$verify_status" -lt 400 ] || fail "visiting the real verification link failed: got $verify_status"
case_pass "real verification link worked"

signin_status="$(curl_net -s -o /dev/null -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt "${HEADERS[@]}" \
  -X POST "$SRC_WC_ORIGIN/api/auth/sign-in/email" \
  -d "{\"email\":\"$USER_EMAIL\",\"password\":\"$USER_PASSWORD\"}")"
[ "$signin_status" = "200" ] || fail "sign-in after verification failed: got $signin_status"
case_pass "real sign-in after verification succeeded"

ORG_SLUG="restore-proof-org-$EMAIL_SUFFIX"
org_body="$(curl_net -s -c /http/jar.txt -b /http/jar.txt "${HEADERS[@]}" \
  -X POST "$SRC_WC_ORIGIN/api/auth/organization/create" \
  -d "{\"name\":\"Restore Proof Org\",\"slug\":\"$ORG_SLUG\"}")"
ORG_ID="$(echo "$org_body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)"
[ -n "$ORG_ID" ] || fail "organization create did not return a real id -- body: $org_body"
case_pass "real organization created (id=$ORG_ID) -- this is the real tenant-scoped state this proof tracks through the restore"

echo "== seeding one real, organization-tagged incident row (no simple creation API on this read-only service) =="
docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$SRC_PG" psql -v ON_ERROR_STOP=1 -U postgres -d reliability_platform -c "
  INSERT INTO reliability.incidents (id, organization_id, source, source_fingerprint, title, severity, status, first_seen_at, last_seen_at, occurrence_starts_at)
  VALUES ('77777777-7777-7777-7777-777777777777', '$ORG_ID', 'restore-proof', 'restore-proof-fingerprint-$RUN_ID', 'Restore proof incident', 'warning', 'open', now(), now(), now());
" >/dev/null
real_incident_check="$(docker exec -e PGPASSWORD="$CONTROL_PLANE_APP_PASSWORD" "$SRC_PG" psql -t -A -U control_plane_app -d reliability_platform \
  -c "SELECT title FROM reliability.incidents WHERE id = '77777777-7777-7777-7777-777777777777';" | tr -d '[:space:]')"
[ "$real_incident_check" = "Restoreproofincident" ] || fail "could not confirm the seeded incident via control_plane_app's own real grant before backup"
case_pass "seeded incident is readable through control_plane_app's real grant before backup (baseline)"

echo ""
echo "== stopping SOURCE application containers (database stays up only long enough to back it up) =="
docker rm -f "$SRC_WC" "$SRC_CP" >/dev/null

echo "== real backup (matches deploy/scripts/backup.sh's own command shape exactly: pg_dumpall --roles-only with password hashes stripped, pg_dump -Fc --schema=reliability --schema=auth --schema=agent_runtime) =="
docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$SRC_PG" pg_dumpall -U postgres --roles-only \
  | grep -v -iE "PASSWORD\s+'(md5|scram-sha-256)" \
  > "$BACKUP_DIR/roles.sql"
docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$SRC_PG" pg_dump -U postgres -d reliability_platform -Fc \
  --schema=reliability --schema=auth --schema=agent_runtime \
  > "$BACKUP_DIR/db.dump"
[ -s "$BACKUP_DIR/roles.sql" ] || fail "roles.sql is empty"
[ -s "$BACKUP_DIR/db.dump" ] || fail "db.dump is empty"
roles_sha="$(shasum -a 256 "$BACKUP_DIR/roles.sql" | awk '{print $1}')"
dump_sha="$(shasum -a 256 "$BACKUP_DIR/db.dump" | awk '{print $1}')"
cat > "$BACKUP_DIR/manifest.json" <<EOF
{"roles_dump_file":"roles.sql","roles_dump_sha256":"$roles_sha","db_dump_file":"db.dump","db_dump_sha256":"$dump_sha"}
EOF
case_pass "real backup produced (roles.sql + db.dump + manifest.json, same shape as backup.sh)"

echo ""
echo "== starting the disposable TARGET PostgreSQL instance (brand new, empty) =="
docker run -d --name "$TGT_PG" --network "$NETWORK_NAME" \
  -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=postgres \
  pgvector/pgvector:pg18 >/dev/null
wait_pg_ready "$TGT_PG" "$BOOTSTRAP_PW"

echo "== running the REAL, now-fixed restore.sh against the TARGET =="
TARGET_PGPASSWORD="$BOOTSTRAP_PW" "$DEPLOY_DIR/scripts/restore.sh" \
  --manifest "$BACKUP_DIR/manifest.json" \
  --docker-network "$NETWORK_NAME" \
  --target-host "$TGT_PG" --target-port 5432 --target-db reliability_platform \
  --target-superuser postgres --target-superuser-password-env TARGET_PGPASSWORD \
  --credentials-out "$CREDS_OUT"
[ -s "$CREDS_OUT" ] || fail "restore.sh did not write the expected credentials file"
case_pass "real restore.sh run completed and wrote new role credentials"

NEW_CONTROL_PLANE_APP_PASSWORD="$(grep '^control_plane_app=' "$CREDS_OUT" | cut -d= -f2-)"
NEW_WEB_CONSOLE_DB_PASSWORD="$(grep '^web_console=' "$CREDS_OUT" | cut -d= -f2-)"
[ -n "$NEW_CONTROL_PLANE_APP_PASSWORD" ] && [ -n "$NEW_WEB_CONSOLE_DB_PASSWORD" ] || fail "could not parse the new role passwords out of --credentials-out"

echo ""
echo "== starting NEW web-console + control-plane against the RESTORED TARGET, using restore.sh's own NEW passwords, enforcement ON =="
docker run -d --name "$TGT_CP" --network "$NETWORK_NAME" \
  -e POSTGRES_HOST="$TGT_PG" -e POSTGRES_USER=control_plane_app -e POSTGRES_PASSWORD="$NEW_CONTROL_PLANE_APP_PASSWORD" \
  -e POSTGRES_DB=reliability_platform \
  -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$SERVICE_ASSERTION_SIGNING_SECRET" \
  "$CP_IMAGE" >/dev/null
TGT_WC_ORIGIN="http://$TGT_WC:3101"
docker run -d --name "$TGT_WC" --network "$NETWORK_NAME" \
  -e POSTGRES_HOST="$TGT_PG" -e POSTGRES_DB=reliability_platform \
  -e WEB_CONSOLE_DB_USER=web_console -e WEB_CONSOLE_DB_PASSWORD="$NEW_WEB_CONSOLE_DB_PASSWORD" \
  -e BETTER_AUTH_SECRET="$BETTER_AUTH_SECRET" \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$SERVICE_ASSERTION_SIGNING_SECRET" \
  -e WEB_CONSOLE_TRUSTED_ORIGIN="$TGT_WC_ORIGIN" \
  -e WEB_CONSOLE_CONTROL_PLANE_URL="http://$TGT_CP:8000" \
  -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
  -e SMTP_HOST="$MAILPIT" -e SMTP_PORT=1025 -e SMTP_FROM_ADDRESS="noreply@restore-proof.test" -e SMTP_SECURITY=none \
  -e ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true \
  "$WC_IMAGE" >/dev/null
wait_http_ready_in_network "http://$TGT_CP:8000/health/live" "target control-plane"
wait_http_ready_in_network "$TGT_WC_ORIGIN/api/health" "target web-console"

echo "== target control-plane + web-console startup logs (diagnostic) =="
docker logs "$TGT_CP" 2>&1 | tail -20
echo "---"
docker logs "$TGT_WC" 2>&1 | tail -20

echo ""
echo "== proving the SAME real user can sign in against the RESTORED target (their Better Auth password hash survived restore untouched -- only Postgres ROLE passwords were rotated) =="
tgt_signin_status="$(curl_net -s -o /http/tgt-signin.json -w '%{http_code}' -c /http/tgt-jar.txt \
  -H "Origin: $TGT_WC_ORIGIN" -H "Content-Type: application/json" \
  -X POST "$TGT_WC_ORIGIN/api/auth/sign-in/email" \
  -d "{\"email\":\"$USER_EMAIL\",\"password\":\"$USER_PASSWORD\"}")"
if [ "$tgt_signin_status" = "200" ]; then
  case_pass "restored user signed in successfully against the RESTORED target web-console"
else
  case_fail "restored user could NOT sign in against the restored target: got $tgt_signin_status, body: $(cat "$HTTP_DIR/tgt-signin.json" 2>/dev/null)"
  echo "== target web-console logs at the moment of sign-in failure (diagnostic) =="
  docker logs "$TGT_WC" 2>&1 | tail -40
fi

org_list_body="$(curl_net -s -b /http/tgt-jar.txt -H "Origin: $TGT_WC_ORIGIN" "$TGT_WC_ORIGIN/api/auth/organization/list")"
if echo "$org_list_body" | python3 -c "import json,sys; items=json.load(sys.stdin); sys.exit(0 if any(o.get('id')=='$ORG_ID' for o in items) else 1)" 2>/dev/null; then
  case_pass "the SAME real organization (id=$ORG_ID) is still present and listed for the restored user"
else
  case_fail "the real organization created before backup was NOT found after restore -- body: $org_list_body"
fi

# CORRECTION ROUND (second pass) -- real finding: being a listed
# MEMBER of an organization is not the same as having it set as the
# session's ACTIVE one -- lib/server/actor.ts's
# requireActorOrRedirect() reads `session.session.activeOrganizationId`
# specifically and REDIRECTS to /organizations (never renders the
# page at all) if it is unset. A brand-new sign-in on the restored
# target starts with no active organization selected, exactly like a
# real first-time browser session would; the real app itself requires
# this same explicit step (Better Auth's own real
# `/organization/set-active` endpoint) before any organization-scoped
# page -- including /incidents -- will render real content instead of
# redirecting.
set_active_status="$(curl_net -s -o /dev/null -w '%{http_code}' -b /http/tgt-jar.txt -c /http/tgt-jar.txt \
  -H "Origin: $TGT_WC_ORIGIN" -H "Content-Type: application/json" \
  -X POST "$TGT_WC_ORIGIN/api/auth/organization/set-active" \
  -d "{\"organizationId\":\"$ORG_ID\"}")"
[ "$set_active_status" = "200" ] || fail "could not set the restored organization as active on the restored target: got $set_active_status"
case_pass "set the real, restored organization as this session's active organization (the same real step a browser performs after sign-in)"

echo "== proving the real, organization-tagged incident survived restore and is still readable through control-plane's own real repository/API code =="
incident_via_sql="$(docker exec -e PGPASSWORD="$NEW_CONTROL_PLANE_APP_PASSWORD" "$TGT_PG" psql -t -A -U control_plane_app -d reliability_platform \
  -c "SELECT title || '|' || organization_id::text FROM reliability.incidents WHERE id = '77777777-7777-7777-7777-777777777777';" 2>/dev/null | tr -d '\r')"
if [ "$incident_via_sql" = "Restore proof incident|$ORG_ID" ]; then
  case_pass "the real incident survived restore with its organization_id intact, readable through control_plane_app's real (narrowed) grant"
else
  case_fail "the real incident did not survive restore correctly, or organization_id is wrong -- got: $incident_via_sql"
fi

echo ""
echo "== enforcement sanity check: an UNAUTHENTICATED direct request to control-plane must now be REJECTED -- =="
echo "== proves CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true is genuinely active, not merely configured =="
unauth_status="$(docker run --rm --network "$NETWORK_NAME" curlimages/curl:8.11.1 -s -o /dev/null -w '%{http_code}' \
  "http://$TGT_CP:8000/api/v1/incidents?source=restore-proof" 2>/dev/null || true)"
if [ "$unauth_status" = "401" ]; then
  case_pass "unauthenticated direct request to control-plane's incidents route correctly rejected (401) -- enforcement is real"
else
  case_fail "unauthenticated direct request to control-plane got $unauth_status, expected 401 -- organization-context enforcement may not actually be active"
fi

echo ""
echo "== proving the REAL, AUTHENTICATED, tenant-scoped read: the restored user's own session reads the restored incident =="
echo "== through web-console's real /incidents page (requireActorOrRedirect + signAssertion -- the same server-side path a real signed-in browser uses) =="
tgt_incidents_html="$(curl_net -s -b /http/tgt-jar.txt -H "Origin: $TGT_WC_ORIGIN" "$TGT_WC_ORIGIN/incidents")"
if echo "$tgt_incidents_html" | grep -qF "Restore proof incident"; then
  case_pass "the restored user's real, authenticated session reads the restored, organization-tagged incident through web-console's own real BFF route"
else
  case_fail "the restored incident's title did not appear in the real, authenticated /incidents page response"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL RESTORE LIVE-LOGIN PROOFS PASSED"
  exit 0
else
  echo "ONE OR MORE RESTORE LIVE-LOGIN PROOFS FAILED" >&2
  exit 1
fi
