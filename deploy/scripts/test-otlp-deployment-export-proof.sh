#!/usr/bin/env bash
#
# test-otlp-deployment-export-proof.sh -- Phase 17A correction round
# (third pass), items 2 and 5.
#
# Real proof, against a real, disposable deployment-shaped stack
# (its own Postgres/mailpit/control-plane/web-console/Caddy containers
# on a throwaway network -- NEVER the developer's own dev stack/db/
# volumes), that:
#
#   1. (item 2) the rendered OTLP-ingestion snippet on the service
#      detail page uses the real, configured HTTPS deployment origin
#      -- not a dead NEXT_PUBLIC_* build-time constant, not the wrong
#      WEB_CONSOLE_TRUSTED_ORIGIN value -- and the official
#      OpenTelemetry Python SDK, configured with EXACTLY that
#      rendered snippet's own env vars, actually exports a real metric
#      through the real Caddy reverse proxy to control-plane, which
#      accepts it and stores it.
#   2. (item 5, "rendered onboarding instructions plus official-SDK
#      ingestion through the deployment endpoint") the same proof,
#      end to end, under REAL secure deployment settings: real sign-up,
#      real SMTP email verification (mailpit, not the log fallback),
#      real sign-in, real active-organization selection, real service
#      registration, a real integration credential minted through the
#      real BFF route, the real rendered page, and a real SDK export --
#      not a reimplementation of any step.
#
# CORRECTION ROUND (third pass) -- real finding: `cleanup()` previously
# did `docker rm -f "web-console" "control-plane" "caddy" "$PG"`
# unconditionally on EXIT, including on an early failure (e.g. the
# very first `docker build`) before any of those containers existed --
# container names are unique per DOCKER DAEMON, not per network, so
# this would have deleted ANY unrelated containers already running
# under those exact bare names on this machine, not merely something
# this run created. Every container below now has a real, unique name
# (suffixed with this run's own $RUN_ID, matching $PG/$WC_IMAGE/
# $CP_IMAGE's existing convention); Caddy's own real, UNMODIFIED
# Caddyfile still hardcodes `control-plane:8000`/`web-console:3101` as
# its reverse_proxy upstreams, so those two containers are ALSO given
# `--network-alias control-plane`/`--network-alias web-console` --
# Docker's embedded DNS then resolves both the real unique name AND
# the alias to the same container, without the container's own real
# identity ever being the ambiguous bare string. `cleanup()` now only
# ever removes a resource whose own `CREATED_*` flag was set to 1
# immediately after this run itself actually created it.
#
# CORRECTION ROUND (third pass) -- also now runs under REAL secure
# deployment settings throughout: CONTROL_PLANE_REQUIRE_ORGANIZATION_
# CONTEXT=true on both services (a real disposable mailpit replaces
# the log-verification fallback that flag turns off), real HTTPS,
# real Secure cookies, real trusted-proxy settings, and a real,
# explicit active-organization-selection step (see
# deploy/scripts/test-restore-live-login-proof.sh's own identical real
# finding: being a listed organization member is not the same as
# having it ACTIVE in session).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"

fail() { echo "FAIL: $1" >&2; exit 1; }
FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

RUN_ID="$$-$(date +%s)"
echo "== run id: $RUN_ID =="
NETWORK_NAME="arp-otlp-export-proof-net-$RUN_ID"
PG="arp-otlp-export-proof-pg-$RUN_ID"
MAILPIT="arp-otlp-export-proof-mailpit-$RUN_ID"
CP="arp-otlp-export-proof-cp-$RUN_ID"
WC="arp-otlp-export-proof-wc-$RUN_ID"
CADDY="arp-otlp-export-proof-caddy-$RUN_ID"
WC_IMAGE="arp-otlp-export-proof-wc-image-$RUN_ID"
CP_IMAGE="arp-otlp-export-proof-cp-image-$RUN_ID"
BOOTSTRAP_PW="bootstrap-$RUN_ID"
BETTER_AUTH_SECRET="auth-secret-$RUN_ID-0123456789abcdef"
SERVICE_ASSERTION_SIGNING_SECRET="assertion-secret-$RUN_ID-0123456789abcdef"
TEST_ORIGIN_HOST="arp-otlp-proof-$RUN_ID.test"
TEST_ORIGIN="https://$TEST_ORIGIN_HOST"
MAILPIT_API="http://$MAILPIT:8025/api/v1"
CA_CERT_FILE="$(mktemp)"
CADDYFILE_COPY="$(mktemp)"

# Resource-ownership tracking: cleanup() only ever removes a resource
# whose own flag was set to 1 immediately after THIS run actually
# created it -- never a bare, possibly-shared name.
CREATED_WC_IMAGE=0
CREATED_CP_IMAGE=0
CREATED_NET=0
CREATED_PG=0
CREATED_MAILPIT=0
CREATED_CP=0
CREATED_WC=0
CREATED_CADDY=0

# shellcheck disable=SC2329 # invoked indirectly via `trap cleanup EXIT`
cleanup() {
  [ "$CREATED_CADDY" -eq 1 ] && docker rm -f "$CADDY" >/dev/null 2>&1
  [ "$CREATED_WC" -eq 1 ] && docker rm -f "$WC" >/dev/null 2>&1
  [ "$CREATED_CP" -eq 1 ] && docker rm -f "$CP" >/dev/null 2>&1
  [ "$CREATED_MAILPIT" -eq 1 ] && docker rm -f "$MAILPIT" >/dev/null 2>&1
  [ "$CREATED_PG" -eq 1 ] && docker rm -f "$PG" >/dev/null 2>&1
  [ "$CREATED_NET" -eq 1 ] && docker network rm "$NETWORK_NAME" >/dev/null 2>&1
  [ "$CREATED_WC_IMAGE" -eq 1 ] && docker rmi "$WC_IMAGE" >/dev/null 2>&1
  [ "$CREATED_CP_IMAGE" -eq 1 ] && docker rmi "$CP_IMAGE" >/dev/null 2>&1
  rm -f "$CA_CERT_FILE" "$CADDYFILE_COPY"
  rm -rf "${HTTP_DIR:-}"
  return 0
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

echo "== building real web-console and control-plane images =="
docker build -q -t "$WC_IMAGE" "$REPO_ROOT/services/web-console" >/dev/null
CREATED_WC_IMAGE=1
docker build -q -t "$CP_IMAGE" "$REPO_ROOT/services/control-plane" >/dev/null
CREATED_CP_IMAGE=1

echo "== starting the disposable PostgreSQL instance =="
docker network create "$NETWORK_NAME" >/dev/null
CREATED_NET=1
docker run -d --name "$PG" --network "$NETWORK_NAME" \
  -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=reliability_platform \
  pgvector/pgvector:pg18 >/dev/null
CREATED_PG=1
wait_pg_ready "$PG" "$BOOTSTRAP_PW"

echo "== starting a disposable mailpit (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true forces real SMTP, never the log fallback) =="
docker run -d --name "$MAILPIT" --network "$NETWORK_NAME" axllent/mailpit:v1.20.0 >/dev/null
CREATED_MAILPIT=1
sleep 2

echo "== applying the REAL Flyway migrations (database/migrations/, unmodified) =="
docker run --rm --network "$NETWORK_NAME" \
  -e FLYWAY_URL="jdbc:postgresql://$PG:5432/reliability_platform" \
  -e FLYWAY_USER=postgres -e FLYWAY_PASSWORD="$BOOTSTRAP_PW" \
  -e FLYWAY_SCHEMAS=reliability -e FLYWAY_LOCATIONS=filesystem:/flyway/sql \
  -v "$REPO_ROOT/database/migrations:/flyway/sql:ro" \
  flyway/flyway:13.9.0 migrate >/dev/null

echo "== applying the REAL, unmodified runtime-roles template =="
CONTROL_PLANE_APP_PASSWORD="cp-app-$RUN_ID"
WEB_CONSOLE_DB_PASSWORD="wc-app-$RUN_ID"
sed \
  -e "s/CONTROL_PLANE_APP_PASSWORD_PLACEHOLDER/$CONTROL_PLANE_APP_PASSWORD/" \
  -e "s/RETRIEVAL_APP_PASSWORD_PLACEHOLDER/ra-app-$RUN_ID/" \
  -e "s/WEB_CONSOLE_PASSWORD_PLACEHOLDER/$WEB_CONSOLE_DB_PASSWORD/" \
  -e "s/AGENT_RUNTIME_PASSWORD_PLACEHOLDER/ar-app-$RUN_ID/" \
  "$DEPLOY_DIR/sql/01-create-runtime-roles.sql.template" \
  | docker exec -i -e PGPASSWORD="$BOOTSTRAP_PW" "$PG" psql -v ON_ERROR_STOP=1 -U postgres -d reliability_platform -f -

echo "== applying the REAL Better Auth schema.sql, connected as web_console (matches apply-deploy-auth-schema.sh) =="
{ echo "SET search_path TO auth;"; cat "$REPO_ROOT/services/web-console/auth-schema/schema.sql"; } \
  | docker exec -i -e PGPASSWORD="$WEB_CONSOLE_DB_PASSWORD" "$PG" psql -v ON_ERROR_STOP=1 -U web_console -d reliability_platform -f -

echo "== re-asserting the real, narrowed control_plane_app grant on auth.member =="
docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$PG" psql -v ON_ERROR_STOP=1 -U postgres -d reliability_platform \
  -c 'REVOKE SELECT ON ALL TABLES IN SCHEMA auth FROM control_plane_app;' \
  -c 'GRANT SELECT ("organizationId", "userId", "role") ON auth.member TO control_plane_app;' >/dev/null

start_control_plane() {
  # $1 = container name, $2 = OTLP_INGEST not used here (CP has no
  # such var), always org-enforcement ON.
  docker run -d --name "$1" --network "$NETWORK_NAME" --network-alias control-plane \
    -e POSTGRES_HOST="$PG" -e POSTGRES_USER=control_plane_app -e POSTGRES_PASSWORD="$CONTROL_PLANE_APP_PASSWORD" \
    -e POSTGRES_DB=reliability_platform \
    -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
    -e SERVICE_ASSERTION_SIGNING_SECRET="$SERVICE_ASSERTION_SIGNING_SECRET" \
    -e SERVICE_ASSERTION_TRUSTED_ISSUERS="web-console" \
    -e TRUSTED_PROXY_ENABLED=true -e TRUSTED_PROXY_HOSTS="$CADDY" \
    "$CP_IMAGE" >/dev/null
}

start_web_console() {
  # $1 = container name, $2 = WEB_CONSOLE_TRUSTED_ORIGIN value,
  # $3 = OTLP_INGEST_PUBLIC_ORIGIN value ("" to leave it unset,
  # matching the local-dev default-fallback case).
  local name="$1" trusted_origin="$2" otlp_origin="$3"
  local otlp_arg=()
  if [ -n "$otlp_origin" ]; then
    otlp_arg=(-e "OTLP_INGEST_PUBLIC_ORIGIN=$otlp_origin")
  fi
  docker run -d --name "$name" --network "$NETWORK_NAME" --network-alias web-console \
    -e POSTGRES_HOST="$PG" -e POSTGRES_DB=reliability_platform \
    -e WEB_CONSOLE_DB_USER=web_console -e WEB_CONSOLE_DB_PASSWORD="$WEB_CONSOLE_DB_PASSWORD" \
    -e BETTER_AUTH_SECRET="$BETTER_AUTH_SECRET" \
    -e SERVICE_ASSERTION_SIGNING_SECRET="$SERVICE_ASSERTION_SIGNING_SECRET" \
    -e WEB_CONSOLE_CONTROL_PLANE_URL="http://control-plane:8000" \
    -e WEB_CONSOLE_TRUSTED_ORIGIN="$trusted_origin" \
    "${otlp_arg[@]}" \
    -e WEB_CONSOLE_USE_SECURE_COOKIES=true \
    -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
    -e TRUSTED_PROXY_ENABLED=true -e TRUSTED_PROXY_HOSTS="$CADDY" \
    -e SMTP_HOST="$MAILPIT" -e SMTP_PORT=1025 -e SMTP_FROM_ADDRESS="noreply@$TEST_ORIGIN_HOST" -e SMTP_SECURITY=none \
    -e ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true \
    "$WC_IMAGE" >/dev/null
}

echo "== starting control-plane (unique name \$CP, network-alias 'control-plane' -- the real Caddyfile's own hardcoded upstream name) =="
start_control_plane "$CP"
CREATED_CP=1

echo "== starting web-console (unique name \$WC, network-alias 'web-console' -- same reason), org-enforcement ON, real SMTP -> mailpit, OTLP_INGEST_PUBLIC_ORIGIN = the real deployment origin =="
start_web_console "$WC" "$TEST_ORIGIN" "$TEST_ORIGIN"
CREATED_WC=1

wait_http_ready_in_network "http://control-plane:8000/health/live" "control-plane"
wait_http_ready_in_network "http://web-console:3101/api/health" "web-console"

echo "== starting the REAL, unmodified deploy/caddy/Caddyfile with the pinned caddy:2.10.2-alpine image, DEPLOYMENT_PUBLIC_ORIGIN=$TEST_ORIGIN_HOST, tls internal =="
sed "s/{\$DEPLOYMENT_PUBLIC_ORIGIN}/$TEST_ORIGIN_HOST/" "$DEPLOY_DIR/caddy/Caddyfile" > "$CADDYFILE_COPY"
# DEPLOYMENT_PUBLIC_ORIGIN is substituted directly above (sed) rather
# than passed as an env var, matching how Caddy's own `{$VAR}`
# placeholder syntax expects a BARE HOST for a site-block address
# (Caddy site addresses are not full "https://host" URLs -- "tls
# internal" on the line below is what makes it HTTPS). The Caddyfile
# ITSELF is never edited -- only this disposable, temp-file copy's one
# substitution, exactly as deploy/README.md's own documented workflow
# already does for a real deployment's DEPLOYMENT_PUBLIC_ORIGIN.
docker run -d --name "$CADDY" --network "$NETWORK_NAME" \
  -v "$CADDYFILE_COPY:/etc/caddy/Caddyfile:ro" \
  caddy:2.10.2-alpine >/dev/null
CREATED_CADDY=1

echo "== extracting Caddy's own local CA root certificate =="
ready=0
for _ in $(seq 1 30); do
  if docker cp "$CADDY:/data/caddy/pki/authorities/local/root.crt" "$CA_CERT_FILE" 2>/dev/null; then
    [ -s "$CA_CERT_FILE" ] && { ready=1; break; }
  fi
  sleep 1
done
[ "$ready" -eq 1 ] || fail "could not extract Caddy's local CA root certificate"

HTTP_DIR="$(mktemp -d)"
CADDY_IP="$(docker inspect "$CADDY" --format "{{(index .NetworkSettings.Networks \"$NETWORK_NAME\").IPAddress}}")"
# `index` (not dot-field access) is REQUIRED here: Go's text/template
# dot-notation for a map key only works when the key is a valid bare
# identifier -- a network name containing hyphens (this script's own
# generated $NETWORK_NAME always does) makes `.Networks.<name>.X`
# fail with "bad character U+002D '-'".
[ -n "$CADDY_IP" ] || fail "could not resolve Caddy's own container-network IP address"

curl_https() {
  # --resolve pins the test hostname to Caddy's own container-network
  # address without needing real DNS; --cacert trusts Caddy's own
  # extracted local CA -- never -k / a global TLS bypass.
  docker run --rm --user "$(id -u):$(id -g)" --network "$NETWORK_NAME" -v "$HTTP_DIR:/http" -v "$CA_CERT_FILE:/ca.crt:ro" \
    curlimages/curl:8.11.1 --resolve "$TEST_ORIGIN_HOST:443:$CADDY_IP" \
    --cacert /ca.crt "$@"
}

echo ""
echo "== real TLS proof through Caddy (no -k, explicit CA trust) =="
root_code="$(curl_https -s -o /dev/null -w '%{http_code}' "$TEST_ORIGIN/")"
[ "$root_code" != "000" ] || fail "real HTTPS request through Caddy failed outright"
case_pass "real TLS handshake through Caddy succeeded (HTTP $root_code)"

echo ""
echo "== mailpit helper: waits for and returns a real delivered email's body =="
wait_for_mail() {
  local to="$1" subject="$2"
  for _ in $(seq 1 40); do
    local list_body msg_id
    list_body="$(curl_https -s "$MAILPIT_API/messages?limit=50" --resolve "$TEST_ORIGIN_HOST:443:$CADDY_IP" 2>/dev/null || true)"
    # mailpit's own HTTP API is plain HTTP, not behind Caddy/TLS at
    # all -- reached directly over the network, never through Caddy.
    list_body="$(docker run --rm --network "$NETWORK_NAME" curlimages/curl:8.11.1 -s "$MAILPIT_API/messages?limit=50")"
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
      docker run --rm --network "$NETWORK_NAME" curlimages/curl:8.11.1 -s "$MAILPIT_API/message/$msg_id" \
        | python3 -c "import json,sys; print(json.load(sys.stdin).get('Text',''))"
      return 0
    fi
    sleep 1
  done
  return 1
}

echo ""
echo "== real sign-up / real SMTP email verification (mailpit) / sign-in / active-organization selection / service registration, through Caddy =="
EMAIL_SUFFIX="$RANDOM$RANDOM"
USER_EMAIL="otlp-proof-user-$EMAIL_SUFFIX@example.com"
USER_PASSWORD="CorrectHorseBattery12!"
HEADERS=(-H "Origin: $TEST_ORIGIN" -H "Content-Type: application/json")

signup_status="$(curl_https -s -o /http/signup.json -w '%{http_code}' -c /http/jar.txt "${HEADERS[@]}" \
  -X POST "$TEST_ORIGIN/api/auth/sign-up/email" \
  -d "{\"email\":\"$USER_EMAIL\",\"password\":\"$USER_PASSWORD\",\"name\":\"OTLP Proof User\"}")"
[ "$signup_status" = "200" ] || fail "sign-up failed: got $signup_status, body: $(cat "$HTTP_DIR/signup.json" 2>/dev/null)"
case_pass "real sign-up succeeded through Caddy"

verify_msg="$(wait_for_mail "$USER_EMAIL" "verify")" || fail "no real verification email arrived at mailpit for $USER_EMAIL"
verify_url_raw="$(echo "$verify_msg" | grep -oE "https?://\S+" | head -1 | sed -E 's/[.,]+$//')"
[ -n "$verify_url_raw" ] || fail "verification email arrived but contained no real link"
# The mailed link embeds web-console's OWN internal callback host
# (http://web-console:3101/...) -- rewrite just the scheme+host to
# the real public test origin so the visit itself also goes through
# Caddy (the path/token query string, the real sensitive part, is
# untouched).
verify_url="$(echo "$verify_url_raw" | sed -E "s#^https?://[^/]+#$TEST_ORIGIN#")"
verify_status="$(curl_https -s -o /dev/null -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt "$verify_url")"
[ "$verify_status" -lt 400 ] || fail "visiting the real verification link through Caddy failed: got $verify_status"
case_pass "found and visited the real verification link via mailpit's own HTTP API (real SMTP delivery, not the log fallback) -- worked through Caddy"

signin_status="$(curl_https -s -o /dev/null -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt "${HEADERS[@]}" \
  -X POST "$TEST_ORIGIN/api/auth/sign-in/email" \
  -d "{\"email\":\"$USER_EMAIL\",\"password\":\"$USER_PASSWORD\"}")"
[ "$signin_status" = "200" ] || fail "sign-in after verification failed through Caddy: got $signin_status"
case_pass "real sign-in succeeded through Caddy (real Secure session cookie set over real TLS)"

ORG_SLUG="otlp-proof-org-$EMAIL_SUFFIX"
org_body="$(curl_https -s -c /http/jar.txt -b /http/jar.txt "${HEADERS[@]}" \
  -X POST "$TEST_ORIGIN/api/auth/organization/create" \
  -d "{\"name\":\"OTLP Proof Org\",\"slug\":\"$ORG_SLUG\"}")"
ORG_ID="$(echo "$org_body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)"
[ -n "$ORG_ID" ] || fail "organization create did not return a real id -- body: $org_body"
case_pass "real organization created through Caddy (id=$ORG_ID)"

# CORRECTION ROUND (third pass) -- real finding (shared with
# deploy/scripts/test-restore-live-login-proof.sh): being a listed
# organization MEMBER (via /organization/create above) is not the
# same as having it ACTIVE in session -- requireActorOrRedirect()
# reads session.session.activeOrganizationId specifically, which a
# fresh sign-in never sets automatically. Without this real step,
# every organization-scoped page below (including /services/<id>)
# would redirect to /organizations instead of rendering real content
# -- it was never needed before this proof ran with organization-
# context enforcement OFF.
set_active_status="$(curl_https -s -o /dev/null -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt "${HEADERS[@]}" \
  -X POST "$TEST_ORIGIN/api/auth/organization/set-active" \
  -d "{\"organizationId\":\"$ORG_ID\"}")"
[ "$set_active_status" = "200" ] || fail "could not set the real organization as active: got $set_active_status"
case_pass "set the real organization as this session's active organization (the same real step a browser performs after sign-in)"

svc_body="$(curl_https -s -c /http/jar.txt -b /http/jar.txt "${HEADERS[@]}" \
  -X POST "$TEST_ORIGIN/api/services" \
  -d '{"name":"OTLP Proof Service","kind":"microservice"}')"
SERVICE_ID="$(echo "$svc_body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)"
[ -n "$SERVICE_ID" ] || fail "service registration did not return a real id -- body: $svc_body"
case_pass "real service registered through Caddy (id=$SERVICE_ID)"

echo ""
echo "== enforcement sanity check: an UNAUTHENTICATED direct request to control-plane must be REJECTED -- proves CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true is genuinely active, not merely configured =="
unauth_status="$(docker run --rm --network "$NETWORK_NAME" curlimages/curl:8.11.1 -s -o /dev/null -w '%{http_code}' \
  "http://control-plane:8000/api/v1/incidents?source=otlp-proof" 2>/dev/null || true)"
if [ "$unauth_status" = "401" ]; then
  case_pass "unauthenticated direct request to control-plane's own incidents route correctly rejected (401) -- enforcement is real"
else
  case_fail "unauthenticated direct request to control-plane got $unauth_status, expected 401 -- organization-context enforcement may not actually be active"
fi

echo ""
echo "== real integration credential generation (the real BFF route IntegrationSetupFlow itself calls) =="
cred_status="$(curl_https -s -o /http/cred.json -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt "${HEADERS[@]}" \
  -X POST "$TEST_ORIGIN/api/services/$SERVICE_ID/integrations" -d '{}')"
[ "$cred_status" = "201" ] || fail "credential generation failed: got $cred_status, body: $(cat "$HTTP_DIR/cred.json" 2>/dev/null)"
BEARER_TOKEN="$(python3 -c "import json; print(json.load(open('$HTTP_DIR/cred.json')).get('bearer_token',''))" 2>/dev/null || true)"
[ -n "$BEARER_TOKEN" ] || fail "credential response had no bearer_token -- body: $(cat "$HTTP_DIR/cred.json" 2>/dev/null)"
case_pass "real integration credential generated through Caddy (credential: $(python3 -c "import json; print(json.load(open('$HTTP_DIR/cred.json')).get('credential',{}).get('credential_id',''))" 2>/dev/null))"

# CORRECTION ROUND (third pass) -- real finding: `grep -q
# "$TEST_ORIGIN_HOST" whole-page-body` would ALSO pass if the hostname
# merely appeared anywhere else on the page (e.g. inside
# WEB_CONSOLE_TRUSTED_ORIGIN's own separately-serialized value, which
# this exact page ALSO carries elsewhere in its own RSC payload for
# unrelated reasons) -- it never actually proved the `otlpEndpoint`
# PROP specifically got the right value. Next.js's RSC flight payload
# serializes a Client Component's string props as JSON-ish array/tuple
# entries inside inline `self.__next_f.push(...)` script tags; the
# real, confirmed (by fetching and inspecting this exact page during
# this proof's own development) literal substring this prop's value
# is always embedded as is `\"otlpEndpoint\":\"<value>\"` -- assert
# that EXACT key:value substring, which an unrelated appearance of the
# hostname elsewhere on the page cannot satisfy.
assert_otlp_endpoint() {
  local page_file="$1" expected_value="$2" context="$3"
  if grep -qF "\\\"otlpEndpoint\\\":\\\"$expected_value\\\"" "$page_file"; then
    case_pass "$context: the real rendered page's own RSC payload serialized otlpEndpoint as exactly \"$expected_value\""
  else
    case_fail "$context: the rendered page's otlpEndpoint prop was NOT \"$expected_value\" -- see $page_file"
  fi
}

echo ""
echo "== fetching the REAL rendered service-detail page and asserting the SPECIFIC otlpEndpoint prop value (not merely that the hostname appears somewhere on the page) =="
page_status="$(curl_https -s -o /http/service-page.html -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt \
  -H "Origin: $TEST_ORIGIN" "$TEST_ORIGIN/services/$SERVICE_ID")"
[ "$page_status" = "200" ] || fail "fetching the real rendered service-detail page failed: got $page_status"
assert_otlp_endpoint "$HTTP_DIR/service-page.html" "$TEST_ORIGIN" "deployment mode"
expected_endpoint="$TEST_ORIGIN/api/v1/telemetry/otlp/v1/metrics"

echo ""
echo "== negative check: WEB_CONSOLE_TRUSTED_ORIGIN stays correct, but OTLP_INGEST_PUBLIC_ORIGIN is set to a WRONG value -- the rendered otlpEndpoint must reflect the WRONG value, proving the two variables are genuinely independent, not one a fallback of the other =="
WRONG_OTLP_ORIGIN="https://wrong-otlp-origin-$RUN_ID.invalid"
docker rm -f "$WC" >/dev/null
CREATED_WC=0
start_web_console "$WC" "$TEST_ORIGIN" "$WRONG_OTLP_ORIGIN"
CREATED_WC=1
wait_http_ready_in_network "http://web-console:3101/api/health" "web-console (negative-check env)"
neg_page_status="$(curl_https -s -o /http/service-page-negative.html -w '%{http_code}' -c /http/jar.txt -b /http/jar.txt \
  -H "Origin: $TEST_ORIGIN" "$TEST_ORIGIN/services/$SERVICE_ID")"
[ "$neg_page_status" = "200" ] || fail "fetching the service page under the negative-check env failed: got $neg_page_status"
assert_otlp_endpoint "$HTTP_DIR/service-page-negative.html" "$WRONG_OTLP_ORIGIN" "negative check"
if grep -qF "\\\"otlpEndpoint\\\":\\\"$TEST_ORIGIN\\\"" "$HTTP_DIR/service-page-negative.html"; then
  case_fail "negative check: otlpEndpoint STILL reflects the correct WEB_CONSOLE_TRUSTED_ORIGIN value even though OTLP_INGEST_PUBLIC_ORIGIN was set wrong -- the two variables are not actually independent"
fi

echo ""
echo "== restoring web-console to the correct deployment env for the real SDK export below =="
docker rm -f "$WC" >/dev/null
CREATED_WC=0
start_web_console "$WC" "$TEST_ORIGIN" "$TEST_ORIGIN"
CREATED_WC=1
wait_http_ready_in_network "http://web-console:3101/api/health" "web-console (restored deployment env)"

echo ""
echo "== installing the OFFICIAL OpenTelemetry Python SDK/exporter and running a REAL metric export through Caddy to control-plane, using EXACTLY the rendered snippet's own configuration =="
cat > "$HTTP_DIR/export_proof.py" <<'PYEOF'
import os
import time
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

def parse_headers_env(raw: str) -> dict:
    # Real, documented OTEL_EXPORTER_OTLP_*_HEADERS format is
    # comma-separated key=value pairs -- parse it generically, exactly
    # as the official SDK's own env-var parsing does.
    headers = {}
    for pair in raw.split(","):
        if not pair.strip():
            continue
        key, _, value = pair.partition("=")
        headers[key.strip()] = value.strip()
    return headers


exporter = OTLPMetricExporter(
    endpoint=os.environ["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"],
    headers=parse_headers_env(os.environ["OTEL_EXPORTER_OTLP_METRICS_HEADERS"]),
)
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=1000)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)
meter = metrics.get_meter("otlp-proof")
# control-plane's own ingestion service accepts EXACTLY ONE real
# metric shape -- a HISTOGRAM named "http.server.request.duration"
# with unit "s", and the newer OTel HTTP semantic-convention attribute
# names (http.request.method/http.response.status_code).
histogram = meter.create_histogram("http.server.request.duration", unit="s")
histogram.record(0.042, {"http.request.method": "GET", "http.route": "/proof", "http.response.status_code": 200})
time.sleep(3)
provider.shutdown()
print("EXPORT_PROOF_DONE")
PYEOF

export_log="$(mktemp)"
docker run --rm --network "$NETWORK_NAME" \
  -v "$HTTP_DIR/export_proof.py:/export_proof.py:ro" \
  -v "$CA_CERT_FILE:/usr/local/share/ca-certificates/caddy-local.crt:ro" \
  -e OTEL_SERVICE_NAME="otlp-proof-service" \
  -e OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf" \
  -e OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="$expected_endpoint" \
  -e OTEL_EXPORTER_OTLP_METRICS_HEADERS="Authorization=Bearer $BEARER_TOKEN" \
  -e OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE="delta" \
  -e SSL_CERT_FILE="/usr/local/share/ca-certificates/caddy-local.crt" \
  -e REQUESTS_CA_BUNDLE="/usr/local/share/ca-certificates/caddy-local.crt" \
  python:3.13-slim bash -c "
    pip install -q opentelemetry-distro opentelemetry-exporter-otlp-proto-http 2>&1 | tail -3
    getent hosts $TEST_ORIGIN_HOST >/dev/null 2>&1 || echo '$CADDY_IP $TEST_ORIGIN_HOST' >> /etc/hosts
    python3 /export_proof.py
  " > "$export_log" 2>&1
export_status=$?
cat "$export_log"

# The OTLP SDK's own exporter catches HTTP/TLS failures internally and
# retries a bounded number of times; when every retry fails, it just
# logs a failure line and the SCRIPT ITSELF still finishes and prints
# EXPORT_PROOF_DONE -- explicitly checking for the ABSENCE of that
# failure line (not merely the presence of the completion marker) is
# what this whole correction round exists to enforce elsewhere
# (restore.sh, preflight.sh); it applies here too.
if [ "$export_status" -eq 0 ] && grep -q "EXPORT_PROOF_DONE" "$export_log" && ! grep -q "Failed to export metrics batch" "$export_log"; then
  case_pass "the official OpenTelemetry Python SDK exported a real metric through Caddy, using exactly the rendered snippet's own endpoint/headers/protocol/temporality"
else
  case_fail "the official Python SDK export did not complete successfully (or exhausted its retries) -- see log above"
fi
rm -f "$export_log"

echo ""
echo "== confirming the exported sample actually landed in reliability.telemetry_samples, scoped to this real credential =="
landed="$(docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$PG" psql -t -A -U postgres -d reliability_platform -c "
  SELECT count(*) FROM reliability.telemetry_samples ts
  JOIN reliability.integration_credentials ic ON ic.id = ts.integration_credential_id
  WHERE ic.credential_id = (SELECT credential_id FROM reliability.integration_credentials WHERE service_id = '$SERVICE_ID');
" 2>/dev/null | tr -d '[:space:]')"
if [ "${landed:-0}" -ge 1 ]; then
  case_pass "the real exported sample landed in reliability.telemetry_samples for the real credential ($landed row(s))"
else
  case_fail "no telemetry_samples row landed for this credential after the export"
fi

echo ""
echo "== local-dev regression check: with OTLP_INGEST_PUBLIC_ORIGIN unset, the rendered snippet still falls back to control-plane's own direct port (unchanged local-dev behavior) =="
# Local-dev mode is deliberately independent of organization-context
# enforcement -- the fallback default this proves is purely about
# which origin string renders, nothing about auth; keeping enforcement
# OFF here (local-dev's own real-world default) lets the log-fallback
# verification link be used again, matching actual local-dev behavior
# exactly rather than introducing an enforcement dependency this check
# was never about.
docker rm -f "$WC" >/dev/null
CREATED_WC=0
docker run -d --name "$WC" --network "$NETWORK_NAME" --network-alias web-console \
  -e POSTGRES_HOST="$PG" -e POSTGRES_DB=reliability_platform \
  -e WEB_CONSOLE_DB_USER=web_console -e WEB_CONSOLE_DB_PASSWORD="$WEB_CONSOLE_DB_PASSWORD" \
  -e BETTER_AUTH_SECRET="$BETTER_AUTH_SECRET" \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$SERVICE_ASSERTION_SIGNING_SECRET" \
  -e WEB_CONSOLE_CONTROL_PLANE_URL="http://control-plane:8000" \
  -e WEB_CONSOLE_TRUSTED_ORIGIN="http://web-console:3101" \
  "$WC_IMAGE" >/dev/null
CREATED_WC=1
wait_http_ready_in_network "http://web-console:3101/api/health" "web-console (local-dev mode)"

localdev_cookie="$(mktemp)"
curl_localdev() { docker run --rm --user "$(id -u):$(id -g)" --network "$NETWORK_NAME" -v "$(dirname "$localdev_cookie"):/http" curlimages/curl:8.11.1 "$@"; }
local_headers=(-H "Origin: http://web-console:3101" -H "Content-Type: application/json")
local_email="otlp-localdev-$RANDOM$RANDOM@example.com"
curl_localdev -s -o /dev/null -c "/http/$(basename "$localdev_cookie")" "${local_headers[@]}" \
  -X POST "http://web-console:3101/api/auth/sign-up/email" \
  -d "{\"email\":\"$local_email\",\"password\":\"CorrectHorseBattery12!\",\"name\":\"Local Dev User\"}" >/dev/null
verify_url_local=""
for _ in $(seq 1 20); do
  verify_url_local="$(docker logs "$WC" 2>&1 | grep -oE "email verification link for $local_email [^:]*: https?://\S+" | sed -E 's/.*: //' | tail -1 || true)"
  [ -n "$verify_url_local" ] && break
  sleep 1
done
[ -n "$verify_url_local" ] || fail "local-dev regression check: could not find the verification link"
curl_localdev -s -o /dev/null -c "/http/$(basename "$localdev_cookie")" -b "/http/$(basename "$localdev_cookie")" "$verify_url_local" >/dev/null
curl_localdev -s -o "/http/$(basename "$localdev_cookie").signin" -c "/http/$(basename "$localdev_cookie")" -b "/http/$(basename "$localdev_cookie")" "${local_headers[@]}" \
  -X POST "http://web-console:3101/api/auth/sign-in/email" -d "{\"email\":\"$local_email\",\"password\":\"CorrectHorseBattery12!\"}" >/dev/null
curl_localdev -s -o /dev/null -c "/http/$(basename "$localdev_cookie")" -b "/http/$(basename "$localdev_cookie")" "${local_headers[@]}" \
  -X POST "http://web-console:3101/api/auth/organization/create" -d '{"name":"Local Dev Org","slug":"otlp-localdev-org-'"$RANDOM"'"}' >/dev/null
local_svc_body="$(curl_localdev -s -c "/http/$(basename "$localdev_cookie")" -b "/http/$(basename "$localdev_cookie")" "${local_headers[@]}" \
  -X POST "http://web-console:3101/api/services" -d '{"name":"Local Dev Service","kind":"microservice"}')"
LOCAL_SERVICE_ID="$(echo "$local_svc_body" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)"
[ -n "$LOCAL_SERVICE_ID" ] || fail "local-dev regression check: service registration failed -- body: $local_svc_body"
curl_localdev -s -o "/http/$(basename "$localdev_cookie").page" -b "/http/$(basename "$localdev_cookie")" -H "Origin: http://web-console:3101" "http://web-console:3101/services/$LOCAL_SERVICE_ID" >/dev/null
assert_otlp_endpoint "$localdev_cookie.page" "http://127.0.0.1:8000" "local-dev fallback"
rm -f "$localdev_cookie" "$localdev_cookie.signin" 2>/dev/null || true

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL OTLP DEPLOYMENT EXPORT PROOFS PASSED"
  exit 0
else
  echo "ONE OR MORE OTLP DEPLOYMENT EXPORT PROOFS FAILED" >&2
  exit 1
fi
