#!/usr/bin/env bash
#
# test-caddy-redaction-proof.sh -- Phase 17A correction round (third
# pass), item 1.
#
# Runs the EXACT, unmodified deploy/caddy/Caddyfile with the EXACT
# pinned image (caddy:2.10.2-alpine) against a lightweight fake
# "web-console" backend that reproduces the three real token-leak
# shapes this Caddyfile exists to redact:
#   1. A verification-query token (?token=...).
#   2. A reset-path token (/api/auth/reset-password/<token>).
#   3. A reset-landing-query token, carried in a real `Location`
#      response header on the real 302 Better Auth issues for a
#      valid reset token.
#
# Proves, against REAL running Caddy (never a reimplementation of its
# config logic): the real client receives fully working links/
# redirects (the real token value, unmodified) while NONE of the three
# token values appear anywhere in Caddy's own captured log output.
#
# Disposable, uniquely-named infra only -- never the developer's own
# dev stack/db/volumes.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEPLOY_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"

FAILED=0
case_pass() { echo "PASS: $1"; }
case_fail() { echo "FAIL: $1" >&2; FAILED=1; }

RUN_ID="$$-$(date +%s)"
NET="arp-caddy-redaction-proof-net-$RUN_ID"
HOST="arp-caddy-redaction-proof-$RUN_ID.test"
WORK_DIR="$(mktemp -d)"

# Caddy's own Caddyfile hardcodes its upstream names (control-plane,
# web-console) -- this proof's backend container is therefore named
# exactly "web-console" on its own, uniquely-named, throwaway network.
# Container names are unique per Docker DAEMON, not per network, so a
# real name collision with anything unrelated would make `docker run`
# fail loudly right here (never silently touch an unrelated
# container) -- a known, accepted tradeoff, documented the same way in
# deploy/scripts/test-otlp-deployment-export-proof.sh.
BACKEND="web-console"
CADDY="arp-caddy-redaction-proof-caddy-$RUN_ID"
CREATED_BACKEND=0
CREATED_CADDY=0
CREATED_NET=0

cleanup() {
  [ "$CREATED_CADDY" -eq 1 ] && docker rm -f "$CADDY" >/dev/null 2>&1 || true
  [ "$CREATED_BACKEND" -eq 1 ] && docker rm -f "$BACKEND" >/dev/null 2>&1 || true
  [ "$CREATED_NET" -eq 1 ] && docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

VERIFY_TOKEN="verifyquerytoken-$RUN_ID-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
RESET_PATH_TOKEN="resetpathtoken-$RUN_ID-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
RESET_LANDING_TOKEN="resetlandingtoken-$RUN_ID-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"

echo "== fake backend reproducing the three real Better Auth leak shapes =="
cat > "$WORK_DIR/backend.py" <<PYEOF
import http.server

VERIFY_TOKEN = "$VERIFY_TOKEN"
RESET_PATH_TOKEN = "$RESET_PATH_TOKEN"
RESET_LANDING_TOKEN = "$RESET_LANDING_TOKEN"

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/auth/verify-email"):
            # Leak shape 1: a real verification-query token.
            assert f"token={VERIFY_TOKEN}" in self.path, self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"verified")
        elif self.path.startswith(f"/api/auth/reset-password/{RESET_PATH_TOKEN}"):
            # Leak shape 2 (the request path itself), redirecting with
            # leak shape 3 (the SAME token, now on the Location
            # header's own landing-page query string) -- the exact
            # real Better Auth behavior for a valid reset token.
            self.send_response(302)
            self.send_header("Location", f"https://app.example/reset-password?token={RESET_LANDING_TOKEN}")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, *a):
        pass

http.server.HTTPServer(("0.0.0.0", 3101), Handler).serve_forever()
PYEOF

echo "== network + fake backend (named 'web-console', matching the real Caddyfile's upstream) =="
docker network create "$NET" >/dev/null
CREATED_NET=1
docker run -d --name "$BACKEND" --network "$NET" \
  -v "$WORK_DIR/backend.py:/backend.py:ro" python:3.13-slim python3 /backend.py >/dev/null
CREATED_BACKEND=1

echo "== starting the REAL, unmodified deploy/caddy/Caddyfile with the pinned caddy:2.10.2-alpine image =="
docker run -d --name "$CADDY" --network "$NET" \
  -e "DEPLOYMENT_PUBLIC_ORIGIN=https://$HOST" \
  -v "$DEPLOY_DIR/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.10.2-alpine >/dev/null
CREATED_CADDY=1
sleep 2
for _ in $(seq 1 15); do
  docker exec "$CADDY" wget -q -O /dev/null --no-check-certificate "https://127.0.0.1:443/" 2>/dev/null && break
  sleep 1
done

CADDY_IP="$(docker inspect "$CADDY" --format "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}")"

run_through_caddy() {
  # $1 = path. Resolves $HOST to Caddy's own container IP, trusts
  # nothing it doesn't need to (no -k): uses --insecure here ONLY
  # because this disposable proof never extracts Caddy's own CA root
  # (the redaction mechanism under test does not depend on TLS trust
  # at all) -- the real deployment Caddyfile's own test-email-flows.sh
  # proof DOES use real CA trust end to end; this lower-level proof's
  # subject is log redaction specifically.
  docker run --rm --network "$NET" --add-host "$HOST:$CADDY_IP" curlimages/curl:8.11.1 \
    -sk -D - -o /dev/null "https://$HOST$1"
}

echo ""
echo "== exercising the real verification-query token through the real Caddy =="
verify_resp="$(run_through_caddy "/api/auth/verify-email?token=$VERIFY_TOKEN&callbackURL=https://x")"
echo "$verify_resp" | head -1
case "$(echo "$verify_resp" | head -1)" in
  *200*) case_pass "the verification link still works (real 200 through Caddy)" ;;
  *) case_fail "the verification link did not return 200 through Caddy -- see: $verify_resp" ;;
esac

echo ""
echo "== exercising the real reset-path token + its real Location redirect through the real Caddy =="
reset_resp="$(run_through_caddy "/api/auth/reset-password/$RESET_PATH_TOKEN?callbackURL=https://x")"
# Printed for diagnostic visibility -- with the one real, sensitive
# value THIS test deliberately generated and is about to assert the
# absence of elsewhere redacted first, consistent with never relying
# on a particular status/outcome to guarantee a secret wasn't
# present in the headers being displayed.
echo "${reset_resp//$RESET_LANDING_TOKEN/REDACTED}"
if echo "$reset_resp" | grep -qi "^HTTP.*302"; then
  case_pass "the reset link still redirects (real 302 through Caddy)"
else
  case_fail "the reset link did not redirect through Caddy -- see: ${reset_resp//$RESET_LANDING_TOKEN/REDACTED}"
fi
if echo "$reset_resp" | grep -qi "^location:.*$RESET_LANDING_TOKEN"; then
  case_pass "the real client receives the real, unmodified reset-landing-query token in Location"
else
  case_fail "the real client did NOT receive the real reset-landing-query token in Location -- see: ${reset_resp//$RESET_LANDING_TOKEN/REDACTED}"
fi

echo ""
echo "== scanning Caddy's own captured logs for all three real token values =="
caddy_logs="$(docker logs "$CADDY" 2>&1)"
for label_token in "verification-query:$VERIFY_TOKEN" "reset-path:$RESET_PATH_TOKEN" "reset-landing-query:$RESET_LANDING_TOKEN"; do
  label="${label_token%%:*}"
  token="${label_token#*:}"
  if echo "$caddy_logs" | grep -qF -- "$token"; then
    case_fail "the real $label token WAS FOUND verbatim in Caddy's own logs -- redaction failed"
  else
    case_pass "the real $label token is absent from Caddy's own logs"
  fi
done

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL CADDY REDACTION PROOFS PASSED"
  exit 0
else
  echo "ONE OR MORE CADDY REDACTION PROOFS FAILED" >&2
  exit 1
fi
