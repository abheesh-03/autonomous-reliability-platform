#!/usr/bin/env bash
#
# test-cross-tenant-and-revocation-proof.sh -- Phase 17A correction
# round, item 5: two of the three "acknowledged missing deployment
# checks":
#   1. Cross-tenant resource denial through the REAL Caddy proxy.
#   2. Revoked-credential rejection with a fresh auth-failure budget.
#
# Real, disposable deployment-topology stack (own Postgres, own
# web-console/control-plane images, own Caddy with `tls internal`) --
# never the developer's own dev stack/db/volumes. Runs with
# CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true (secure-deployment
# mode), so email verification requires real SMTP -- uses the same
# disposable mailpit receiver deploy/scripts/test-email-flows.py
# already uses.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$DEPLOY_DIR/.." &>/dev/null && pwd)"

fail() { echo "FAIL: $1" >&2; exit 1; }

RUN_ID="$$-$(date +%s)"
NET="arp-xtenant-proof-net-$RUN_ID"
PG="arp-xtenant-proof-pg-$RUN_ID"
MAILPIT="arp-xtenant-proof-mailpit-$RUN_ID"
CP="arp-xtenant-proof-cp-$RUN_ID"
WC="arp-xtenant-proof-wc-$RUN_ID"
CADDY="arp-xtenant-proof-caddy-$RUN_ID"
CP_IMG="arp-xtenant-proof-cp-img-$RUN_ID"
WC_IMG="arp-xtenant-proof-wc-img-$RUN_ID"
BOOTSTRAP_PW="bootstrap-$RUN_ID"
HOST="arp-xtenant-$RUN_ID.test"
ORIGIN="https://$HOST"
CADDY_CRT_DIR="$(mktemp -d)"

cleanup() {
  docker rm -f "$CADDY" "$WC" "$CP" "$MAILPIT" "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker rmi "$CP_IMG" "$WC_IMG" >/dev/null 2>&1 || true
  rm -rf "$CADDY_CRT_DIR"
}
trap cleanup EXIT

echo "== network + disposable postgres =="
docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" \
  -e POSTGRES_PASSWORD="$BOOTSTRAP_PW" -e POSTGRES_DB=proofdb pgvector/pgvector:pg18 >/dev/null
ready=0
for _ in $(seq 1 60); do
  docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$PG" psql -U postgres -d proofdb -c "SELECT 1;" >/dev/null 2>&1 && { ready=1; break; }
  sleep 1
done
[ "$ready" -eq 1 ] || fail "postgres never became ready"

echo "== real Flyway migrations + real runtime-roles template + real auth schema =="
docker run --rm --network "$NET" \
  -e FLYWAY_URL="jdbc:postgresql://$PG:5432/proofdb" -e FLYWAY_USER=postgres -e FLYWAY_PASSWORD="$BOOTSTRAP_PW" \
  -e FLYWAY_SCHEMAS=reliability -e FLYWAY_LOCATIONS=filesystem:/flyway/sql \
  -v "$REPO_ROOT/database/migrations:/flyway/sql:ro" flyway/flyway:13.9.0 migrate >/dev/null

CP_DB_PW="cp-$RUN_ID" WC_DB_PW="wc-$RUN_ID" RA_DB_PW="ra-$RUN_ID" AR_DB_PW="ar-$RUN_ID"
sed \
  -e "s/CONTROL_PLANE_APP_PASSWORD_PLACEHOLDER/$CP_DB_PW/" \
  -e "s/RETRIEVAL_APP_PASSWORD_PLACEHOLDER/$RA_DB_PW/" \
  -e "s/WEB_CONSOLE_PASSWORD_PLACEHOLDER/$WC_DB_PW/" \
  -e "s/AGENT_RUNTIME_PASSWORD_PLACEHOLDER/$AR_DB_PW/" \
  "$DEPLOY_DIR/sql/01-create-runtime-roles.sql.template" \
  | docker exec -i -e PGPASSWORD="$BOOTSTRAP_PW" "$PG" psql -v ON_ERROR_STOP=1 -U postgres -d proofdb -f - >/dev/null

docker exec -i -e PGPASSWORD="$WC_DB_PW" "$PG" psql -v ON_ERROR_STOP=1 -U web_console -d proofdb -f - >/dev/null <<SQLEOF
SET search_path TO auth;
$(cat "$REPO_ROOT/services/web-console/auth-schema/schema.sql")
SQLEOF

docker exec -e PGPASSWORD="$BOOTSTRAP_PW" "$PG" psql -v ON_ERROR_STOP=1 -U postgres -d proofdb \
  -c 'REVOKE SELECT ON ALL TABLES IN SCHEMA auth FROM control_plane_app;' \
  -c 'GRANT SELECT ("organizationId", "userId", "role") ON auth.member TO control_plane_app;' >/dev/null

echo "== disposable mailpit (SMTP required: CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true forces real SMTP) =="
docker run -d --name "$MAILPIT" --network "$NET" axllent/mailpit:v1.20.0 >/dev/null
sleep 2

echo "== building real control-plane + web-console images =="
docker build -q -t "$CP_IMG" "$REPO_ROOT/services/control-plane" >/dev/null
docker build -q -t "$WC_IMG" "$REPO_ROOT/services/web-console" >/dev/null

BETTER_AUTH_SECRET="auth-secret-$RUN_ID-0123456789abcdef0123456789abcdef"
SVC_SIGN_SECRET="svc-secret-$RUN_ID-0123456789abcdef0123456789abcdef"
WEBHOOK_TOKEN="webhook-$RUN_ID"

echo "== starting control-plane =="
docker run -d --name "$CP" --network "$NET" \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 -e POSTGRES_USER=control_plane_app -e POSTGRES_PASSWORD="$CP_DB_PW" -e POSTGRES_DB=proofdb \
  -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true \
  -e SERVICE_ASSERTION_SIGNING_SECRET="$SVC_SIGN_SECRET" \
  -e CONTROL_PLANE_WEBHOOK_TOKEN="$WEBHOOK_TOKEN" \
  -e CONTROL_PLANE_ALLOW_LEGACY_INGESTION=false \
  -e TRUSTED_PROXY_ENABLED=true -e TRUSTED_PROXY_HOSTS="$CADDY" \
  "$CP_IMG" >/dev/null

echo "== starting web-console (SMTP -> mailpit) =="
docker run -d --name "$WC" --network "$NET" \
  -e POSTGRES_HOST="$PG" -e POSTGRES_PORT=5432 -e WEB_CONSOLE_DB_USER=web_console -e WEB_CONSOLE_DB_PASSWORD="$WC_DB_PW" -e POSTGRES_DB=proofdb \
  -e BETTER_AUTH_SECRET="$BETTER_AUTH_SECRET" -e SERVICE_ASSERTION_SIGNING_SECRET="$SVC_SIGN_SECRET" \
  -e WEB_CONSOLE_TRUSTED_ORIGIN="$ORIGIN" -e OTLP_INGEST_PUBLIC_ORIGIN="$ORIGIN" \
  -e WEB_CONSOLE_USE_SECURE_COOKIES=true -e WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS=false \
  -e CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT=true -e TRUSTED_PROXY_ENABLED=true -e TRUSTED_PROXY_HOSTS="$CADDY" \
  -e WEB_CONSOLE_CONTROL_PLANE_URL="http://$CP:8000" \
  -e SMTP_HOST="$MAILPIT" -e SMTP_PORT=1025 -e SMTP_FROM_ADDRESS="noreply@$HOST" -e SMTP_SECURITY=none \
  -e ALLOW_INSECURE_SMTP_FOR_LOCAL_PROOF=true \
  "$WC_IMG" >/dev/null

echo "== waiting for web-console/control-plane to accept connections =="
for name in "$CP:8000" "$WC:3101"; do
  host="${name%%:*}"; port="${name##*:}"
  ok=0
  for _ in $(seq 1 40); do
    docker run --rm --network "$NET" curlimages/curl:8.11.1 -sf "http://$host:$port/" -o /dev/null 2>/dev/null && { ok=1; break; }
    docker run --rm --network "$NET" curlimages/curl:8.11.1 -s -o /dev/null -w '%{http_code}' "http://$host:$port/" 2>/dev/null | grep -qE '^[0-9]' && { ok=1; break; }
    sleep 1
  done
  [ "$ok" -eq 1 ] || fail "$name never responded"
done

echo "== control-plane + web-console startup logs (diagnostic) =="
docker logs "$CP" 2>&1 | tail -20
echo "---"
docker logs "$WC" 2>&1 | tail -20

echo "== starting Caddy (tls internal) =="
cat > "$CADDY_CRT_DIR/Caddyfile" <<CADDYEOF
{
  admin off
}
$HOST {
  tls internal
  encode gzip zstd
  @telemetry_ingest {
    method POST
    path /api/v1/telemetry/otlp/v1/metrics
  }
  handle @telemetry_ingest {
    reverse_proxy $CP:8000 {
      header_up X-Forwarded-For {http.request.remote.host}
      header_up X-Forwarded-Proto {http.request.scheme}
      header_up Host {http.request.host}
    }
  }
  handle {
    reverse_proxy $WC:3101 {
      header_up X-Forwarded-For {http.request.remote.host}
      header_up X-Forwarded-Proto {http.request.scheme}
      header_up Host {http.request.host}
    }
  }
}
CADDYEOF
docker run -d --name "$CADDY" --network "$NET" \
  -v "$CADDY_CRT_DIR/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.10.2-alpine >/dev/null
sleep 2
for _ in $(seq 1 15); do
  docker exec "$CADDY" wget -q -O /dev/null --no-check-certificate "https://127.0.0.1:443/" 2>/dev/null && break
  sleep 1
done

echo "== extracting Caddy's local CA root =="
for _ in $(seq 1 15); do
  docker cp "$CADDY":/data/caddy/pki/authorities/local/root.crt "$CADDY_CRT_DIR/root.crt" 2>/dev/null && break
  sleep 1
done
[ -s "$CADDY_CRT_DIR/root.crt" ] || fail "could not extract Caddy's CA root"

echo "== running the real HTTP proof (python, same disposable network -- no host port publishing, no macOS host-networking dependency) =="
CADDY_IP="$(docker inspect "$CADDY" --format "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}")"
docker run --rm --network "$NET" \
  --add-host "$HOST:$CADDY_IP" \
  -v "$CADDY_CRT_DIR/root.crt:/root.crt:ro" \
  -e ORIGIN="$ORIGIN" -e HOST="$HOST" -e MAILPIT_HOST="$MAILPIT" \
  python:3.13-slim bash -c '
set -e
pip install -q requests
python3 -c "
import os, re, time, requests, random, string

ORIGIN = os.environ[\"ORIGIN\"]
HOST = os.environ[\"HOST\"]
MAILPIT_API = f\"http://{os.environ[\"MAILPIT_HOST\"]}:8025/api/v1\"
CA = \"/root.crt\"
BASE = f\"https://{HOST}\"

FAILED = []
def check(label, cond, detail=\"\"):
    print((\"PASS: \" if cond else \"FAIL: \") + label + ((\" \" + detail) if detail else \"\"))
    if not cond:
        FAILED.append(label)

def rand():
    return \"\".join(random.choices(string.ascii_lowercase + string.digits, k=10))

def wait_mail(to, subj, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f\"{MAILPIT_API}/messages\", params={\"limit\": 50}); r.raise_for_status()
        for m in r.json().get(\"messages\", []):
            if to in [t[\"Address\"] for t in m.get(\"To\", [])] and subj.lower() in m.get(\"Subject\",\"\").lower():
                d = requests.get(f\"{MAILPIT_API}/message/{m[\"ID\"]}\"); d.raise_for_status(); return d.json()
        time.sleep(0.5)
    raise TimeoutError(f\"no mail to {to}\")

def extract_url(text):
    return re.search(r\"https?://\\S+\", text).group(0).rstrip(\".,\")

def signup_verify_signin(email, password, name):
    s = requests.Session(); s.headers.update({\"Origin\": ORIGIN})
    r = s.post(f\"{BASE}/api/auth/sign-up/email\", json={\"email\": email, \"password\": password, \"name\": name}, verify=CA)
    if r.status_code != 200:
        print(f\"diagnostic: sign-up failed: status={r.status_code} body={r.text!r}\")
    assert r.status_code == 200, r.text
    msg = wait_mail(email, \"verify\")
    link = extract_url(msg[\"Text\"])
    r = s.get(link, verify=CA, allow_redirects=True)
    assert r.status_code < 400
    r = s.post(f\"{BASE}/api/auth/sign-in/email\", json={\"email\": email, \"password\": password}, verify=CA)
    assert r.status_code == 200, r.text
    return s

# --- Org A: creates a service ---
email_a = f\"xtenant-a-{rand()}@example.com\"
sess_a = signup_verify_signin(email_a, \"CorrectHorseBattery12!\", \"Org A User\")
r = sess_a.post(f\"{BASE}/api/auth/organization/create\", json={\"name\": \"Org A\", \"slug\": f\"org-a-{rand()}\"}, verify=CA)
check(\"org A create succeeds\", r.status_code == 200, f\"got {r.status_code}: {r.text[:200]}\")

r = sess_a.post(f\"{BASE}/api/services\", json={\"name\": \"org-a-service\", \"kind\": \"other\"}, verify=CA)
check(\"org A service create succeeds\", r.status_code == 201, f\"got {r.status_code}: {r.text[:200]}\")
service_a_id = r.json().get(\"id\") if r.status_code == 201 else None

# a fresh integration credential on org A service, for the revocation proof
r = sess_a.post(f\"{BASE}/api/services/{service_a_id}/integrations\", json={}, verify=CA)
check(\"org A credential generate succeeds\", r.status_code == 201, f\"got {r.status_code}: {r.text[:200]}\")
cred = r.json() if r.status_code == 201 else {}
credential_id = cred.get(\"credential\", {}).get(\"id\")
bearer_token = cred.get(\"bearer_token\")
check(\"a real bearer token was issued\", bool(bearer_token))

# --- Org B: separate user/org, attempts to read Org A service ---
email_b = f\"xtenant-b-{rand()}@example.com\"
sess_b = signup_verify_signin(email_b, \"CorrectHorseBattery56!\", \"Org B User\")
r = sess_b.post(f\"{BASE}/api/auth/organization/create\", json={\"name\": \"Org B\", \"slug\": f\"org-b-{rand()}\"}, verify=CA)
check(\"org B create succeeds\", r.status_code == 200, f\"got {r.status_code}: {r.text[:200]}\")

r = sess_b.get(f\"{BASE}/services/{service_a_id}\", verify=CA, allow_redirects=False)
check(\"CROSS-TENANT: org B cannot read org A service through the real proxy\", r.status_code == 404, f\"got {r.status_code}\")

r = sess_b.get(f\"{BASE}/api/services/{service_a_id}/integrations\", verify=CA)
check(\"CROSS-TENANT: org B cannot list org A integration credentials\", r.status_code in (404, 403), f\"got {r.status_code}\")

# --- Revocation, with a FRESH failure budget (no prior auth-failure requests against this stack before this point) ---
r = sess_a.post(f\"{BASE}/api/services/{service_a_id}/integrations/{credential_id}/revoke\", verify=CA)
check(\"org A can revoke its own credential\", r.status_code == 200, f\"got {r.status_code}: {r.text[:200]}\")

for i in range(3):
    r = requests.post(f\"{BASE}/api/v1/telemetry/otlp/v1/metrics\",
                       headers={\"Authorization\": f\"Bearer {bearer_token}\", \"Content-Type\": \"application/json\"},
                       data=\"{\\\"resourceMetrics\\\":[]}\", verify=CA)
    check(f\"REVOKED CREDENTIAL rejected on attempt {i+1}/3 (fresh budget, well under the 10-failure limit)\",
          r.status_code == 401, f\"got {r.status_code}: {r.text[:150]}\")

if FAILED:
    print(); print(\"RESULT: FAILED -\", FAILED); raise SystemExit(1)
print(); print(\"RESULT: ALL CROSS-TENANT AND REVOCATION CHECKS PASSED\")
"
'
