#!/usr/bin/env python3
"""Phase 17A item 4: real proof of email verification, organization
invitation, and password reset -- against the REAL, running
deployment stack, through the REAL Caddy reverse proxy, with REAL
email delivery captured by a disposable, non-public local test SMTP
receiver (mailpit, deploy/docker-compose.test-smtp.yml).

Never prints a real token/link/full email body -- only short,
truncated prefixes where evidence is shown, and only PASS/FAIL lines.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import socket
import string
import sys
import time
import urllib.parse

import requests

# CORRECTION ROUND: these three were previously hardcoded module
# constants -- "https://arp-deploy.test" (CI actually sets
# DEPLOYMENT_PUBLIC_ORIGIN=https://arp-deploy-ci.test; a completely
# different SNI/Host name with no matching Caddy site block for it at
# all), "deploy/caddy_root.crt" (CI writes the extracted CA to
# /tmp/caddy_root.crt, never that path), and mailpit's fixed local
# port (coincidentally correct today only because it happens to match
# deploy/docker-compose.test-smtp.yml's own hardcoded published port,
# an implicit coupling between two files that agree only by luck).
# Every real value now comes from the command line, with today's
# values kept as DEFAULTS so a manual local run needs no flags.
ORIGIN = ""
MAILPIT_API = ""
CA_CERT = ""
_RESOLVED_HOST = ""

_real_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(host, *args, **kwargs):
    # Redirects ONLY the actual configured origin's hostname (derived
    # from --origin, never a hardcoded literal) to 127.0.0.1 -- every
    # other lookup (e.g. mailpit's own 127.0.0.1 API) passes through
    # unchanged.
    if host == _RESOLVED_HOST:
        host = "127.0.0.1"
    return _real_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _patched_getaddrinfo

FAILED = False


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILED
    if condition:
        print(f"PASS: {label}")
    else:
        FAILED = True
        print(f"FAIL: {label} {detail}")


def safe_url_prefix(url: str) -> str:
    """CORRECTION ROUND (third pass) -- real finding: diagnostic
    detail strings elsewhere in this file previously used a blind
    character-count slice (e.g. `url[:40]`) to avoid printing a real
    token -- correct only by coincidence, for exactly the origin
    strings this script happens to use today; a longer origin, or a
    `detail` string only ever printed on the FAILURE path (which
    `check()` does for every one of these), could print a real,
    currently-valid token into this script's own stdout/CI log.
    Returns scheme+host+path only -- NEVER the query string (leak
    paths #1 and #3: `?token=...`), and if the path itself contains
    `reset-password/<token>` (leak path #2), everything after that
    segment is also replaced -- regardless of string length."""
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path
    marker = "/reset-password/"
    idx = path.find(marker)
    if idx != -1:
        path = path[: idx + len(marker)] + "<redacted>"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def check_rejected(label: str, response: requests.Response, *, allow_redirect: bool = False) -> None:
    """CORRECTION ROUND: replaces the previous bare `status_code !=
    200` pattern used for every "this must be rejected" assertion --
    that pattern is satisfied just as well by a crashed 500, an
    unrelated 3xx redirect, or a 429 from an EARLIER request's rate
    limit already having tripped, none of which are evidence that the
    specific rejection under test actually happened. Requires a real
    4xx client-error response (optionally also a redirect, for routes
    that reject via redirect) and explicitly calls out the two
    specific false-positive shapes that most commonly slip through."""
    status = response.status_code
    if status == 429:
        check(label, False, "got 429 -- the rate limiter already tripped from an earlier request; not valid proof of this specific rejection")
        return
    if status >= 500:
        check(label, False, f"got {status} -- a server error is never valid proof of a correct rejection")
        return
    ok = (400 <= status < 500) or (allow_redirect and status in (302, 303, 307, 308))
    check(label, ok, f"got {status}")


def rand_suffix() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def mailpit_wait_for_message(to_address: str, subject_contains: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(f"{MAILPIT_API}/messages", params={"limit": 50})
        resp.raise_for_status()
        for msg in resp.json().get("messages", []):
            to_list = [t["Address"] for t in msg.get("To", [])]
            if to_address in to_list and subject_contains.lower() in msg.get("Subject", "").lower():
                detail = requests.get(f"{MAILPIT_API}/message/{msg['ID']}")
                detail.raise_for_status()
                return detail.json()
        time.sleep(0.5)
    raise TimeoutError(f"no message to {to_address} with subject containing {subject_contains!r} within {timeout}s")


def extract_url(text: str) -> str:
    match = re.search(r"https?://\S+", text)
    if not match:
        raise ValueError("no URL found in message body")
    return match.group(0).rstrip(".,")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://arp-deploy.test", help="the real, configured DEPLOYMENT_PUBLIC_ORIGIN (e.g. CI's own https://arp-deploy-ci.test)")
    parser.add_argument("--ca-cert", default="deploy/caddy_root.crt", help="path to the extracted Caddy local CA root certificate")
    parser.add_argument("--mailpit-api", default="http://127.0.0.1:18025/api/v1", help="the disposable test SMTP receiver's own HTTP API base URL")
    parser.add_argument(
        "--token-scan-file",
        default=None,
        help=(
            "CORRECTION ROUND (second pass): if given, every real "
            "verification/reset token this run actually generates is "
            "written here (one per line, mode 600, created fresh -- "
            "refuses to run if the path already exists) so a caller "
            "can scan Caddy's own captured access/error logs for "
            "these EXACT values after this script exits, without this "
            "script itself ever printing a token anywhere. The file "
            "is this script's own responsibility to write; the "
            "caller is responsible for deleting it after scanning."
        ),
    )
    return parser.parse_args()


_CAPTURED_TOKENS: list[str] = []


def _extract_token_from_query(url: str) -> str:
    query = urllib.parse.urlsplit(url).query
    values = urllib.parse.parse_qs(query).get("token", [])
    return values[0] if values else ""


def _capture_token(value: str) -> None:
    if value:
        _CAPTURED_TOKENS.append(value)


def main() -> int:
    global ORIGIN, MAILPIT_API, CA_CERT, _RESOLVED_HOST
    args = _parse_args()
    ORIGIN = args.origin.rstrip("/")
    MAILPIT_API = args.mailpit_api.rstrip("/")
    CA_CERT = args.ca_cert
    _RESOLVED_HOST = urllib.parse.urlsplit(ORIGIN).hostname or ""

    if args.token_scan_file:
        if os.path.exists(args.token_scan_file):
            print(f"FAIL: --token-scan-file ({args.token_scan_file}) already exists -- refusing to overwrite", file=sys.stderr)
            return 1
        try:
            return _run_flows()
        finally:
            # Written regardless of success/failure -- whatever
            # tokens were actually captured before a failure are
            # still real, still worth scanning for.
            fd = os.open(args.token_scan_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                for token in _CAPTURED_TOKENS:
                    f.write(token + "\n")
    return _run_flows()


def _run_flows() -> int:

    # A real browser always sends an Origin header on these
    # same-origin fetch() calls -- web-console's own BFF origin guard
    # (lib/server/origin-guard.ts) and Better Auth's own trustedOrigins
    # check both require it. Plain `requests` calls do not send one by
    # default, so it is set explicitly here to behave like a real
    # client, not to bypass anything.
    headers = {"Origin": ORIGIN}
    session_a = requests.Session()
    session_a.headers.update(headers)
    session_b = requests.Session()
    session_b.headers.update(headers)

    email_a = f"phase17a-usera-{rand_suffix()}@example.com"
    email_b = f"phase17a-userb-{rand_suffix()}@example.com"
    password_a = "CorrectHorseBattery12!"
    new_password_a = "DifferentHorseBattery34!"
    password_b = "CorrectHorseBattery56!"

    print("=== STEP 1: real sign-up (user A) ===")
    r = session_a.post(
        f"{ORIGIN}/api/auth/sign-up/email",
        json={"email": email_a, "password": password_a, "name": "Phase17A User A"},
        verify=CA_CERT,
    )
    check("sign-up/email (user A) returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    print("=== STEP 2: fetch the REAL verification email from the disposable test receiver ===")
    msg = mailpit_wait_for_message(email_a, "verify")
    verify_url = extract_url(msg["Text"])
    check("verification email contains a real link", bool(verify_url), f"(prefix: {safe_url_prefix(verify_url)})")
    _capture_token(_extract_token_from_query(verify_url))

    print("=== STEP 3: sign-in BEFORE verification is rejected ===")
    presign = requests.Session()
    presign.headers.update(headers)
    r = presign.post(f"{ORIGIN}/api/auth/sign-in/email", json={"email": email_a, "password": password_a}, verify=CA_CERT)
    check_rejected("sign-in before verification is rejected", r)

    print("=== STEP 4: visit the real verification link ===")
    r = session_a.get(verify_url, verify=CA_CERT, allow_redirects=True)
    check("visiting the real verification link succeeds", r.status_code < 400, f"got {r.status_code}")

    print("=== STEP 5: sign-in AFTER verification succeeds ===")
    r = session_a.post(f"{ORIGIN}/api/auth/sign-in/email", json={"email": email_a, "password": password_a}, verify=CA_CERT)
    check("sign-in after verification succeeds", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    print("=== STEP 6: invalid/fabricated verification token is rejected ===")
    fake_verify = verify_url.replace("token=", "token=fabricated-" + rand_suffix() + "-")
    r = requests.get(fake_verify, headers=headers, verify=CA_CERT, allow_redirects=False)
    if r.status_code == 429:
        check("fabricated verification token is rejected", False, "got 429 -- rate limiter already tripped, not valid proof")
    elif r.status_code >= 500:
        check("fabricated verification token is rejected", False, f"got {r.status_code} -- a server error is never valid proof")
    else:
        rejected = (400 <= r.status_code < 500) or (
            r.status_code in (302, 303, 307, 308) and "error" in r.headers.get("location", "")
        )
        check("fabricated verification token is rejected", rejected, f"got {r.status_code} location={safe_url_prefix(r.headers.get('location', ''))}")

    print("=== STEP 7: organization + invitation flow (user B) ===")
    r = session_a.post(f"{ORIGIN}/api/auth/organization/create", json={"name": "Phase17A Org", "slug": f"phase17a-{rand_suffix()}"}, verify=CA_CERT)
    check("organization create succeeds", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    org = r.json() if r.status_code == 200 else {}
    org_id = org.get("id") if isinstance(org, dict) else None

    r = session_a.post(
        f"{ORIGIN}/api/auth/organization/invite-member",
        json={"email": email_b, "role": "VIEWER", "organizationId": org_id},
        verify=CA_CERT,
    )
    check("invitation create succeeds", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    invitation = r.json() if r.status_code == 200 else {}
    invitation_id = invitation.get("id") if isinstance(invitation, dict) else None

    # Sign up user B (unverified) and attempt to accept the invitation
    # BEFORE verifying -- must be denied (Phase 14 correction round,
    # Issue 5: accept/reject requires a verified email).
    r = session_b.post(f"{ORIGIN}/api/auth/sign-up/email", json={"email": email_b, "password": password_b, "name": "Phase17A User B"}, verify=CA_CERT)
    check("sign-up/email (user B) returns 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    r = session_b.post(f"{ORIGIN}/api/auth/organization/accept-invitation", json={"invitationId": invitation_id}, verify=CA_CERT)
    check_rejected("unverified user B cannot accept the invitation", r)

    msg_b = mailpit_wait_for_message(email_b, "verify")
    verify_url_b = extract_url(msg_b["Text"])
    _capture_token(_extract_token_from_query(verify_url_b))
    r = session_b.get(verify_url_b, verify=CA_CERT, allow_redirects=True)
    check("user B's real verification link works", r.status_code < 400, f"got {r.status_code}")

    r = session_b.post(f"{ORIGIN}/api/auth/organization/accept-invitation", json={"invitationId": invitation_id}, verify=CA_CERT)
    check("verified user B CAN accept the invitation", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    print("=== STEP 8: password reset flow (user A) ===")
    r = session_a.post(f"{ORIGIN}/api/auth/request-password-reset", json={"email": email_a, "redirectTo": "/reset-password"}, verify=CA_CERT)
    check("request-password-reset returns 200 (never reveals existence either way)", r.status_code == 200, f"got {r.status_code}")

    reset_msg = mailpit_wait_for_message(email_a, "reset")
    reset_url = extract_url(reset_msg["Text"])
    token_match = re.search(r"/reset-password/([^?\s]+)", reset_url)
    check("reset email contains a real single-use token", bool(token_match), f"(prefix: {safe_url_prefix(reset_url)})")
    reset_token = token_match.group(1) if token_match else ""
    _capture_token(reset_token)

    # CORRECTION ROUND (second pass): previously extracted the token
    # from the email BODY and called the POST API directly, never
    # actually visiting the real emailed GET link at all -- so the
    # real server-side redirect this flow depends on (Better Auth's
    # own `/api/auth/reset-password/:token` handler 302s to
    # `<callbackURL>?token=<token>`, echoing the SAME raw token into
    # its own `Location` response header) was never exercised by this
    # proof, only asserted indirectly. Visiting it for real is also
    # what actually exercises the Caddy log-redaction fix for this
    # exact leak path (see deploy/caddy/Caddyfile).
    landing = requests.get(reset_url, headers=headers, verify=CA_CERT, allow_redirects=False)
    check(
        "visiting the real reset link redirects (302) to the landing page",
        landing.status_code in (301, 302, 303, 307, 308),
        f"got {landing.status_code}",
    )
    redirect_location = landing.headers.get("location", "")
    check(
        "the redirect's Location carries the SAME real token back to the landing page",
        _extract_token_from_query(redirect_location) == reset_token and bool(reset_token),
        # CORRECTION ROUND (third pass): previously `redirect_location[:60]`
        # -- this is the ONE real, valid, currently-active reset
        # token, carried in the query string this check is itself
        # testing for; a 60-character slice leaked a real prefix of
        # it into this script's own diagnostic output whenever this
        # specific check failed. `safe_url_prefix` strips the query
        # string entirely rather than relying on any length
        # assumption.
        f"location prefix: {safe_url_prefix(redirect_location)} (query string withheld)",
    )
    final_landing = requests.get(redirect_location, headers=headers, verify=CA_CERT, allow_redirects=True) if redirect_location else None
    check(
        "the final landing page (the real reset-password route) loads",
        final_landing is not None and final_landing.status_code < 400,
        f"got {final_landing.status_code if final_landing else 'no redirect to follow'}",
    )

    r = requests.post(f"{ORIGIN}/api/auth/reset-password", json={"newPassword": new_password_a, "token": reset_token}, headers=headers, verify=CA_CERT)
    check("reset-password with the real token succeeds", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    print("=== STEP 9: old password rejected, new password works ===")
    r = requests.post(f"{ORIGIN}/api/auth/sign-in/email", json={"email": email_a, "password": password_a}, headers=headers, verify=CA_CERT)
    check_rejected("OLD password no longer works", r)
    r = requests.post(f"{ORIGIN}/api/auth/sign-in/email", json={"email": email_a, "password": new_password_a}, headers=headers, verify=CA_CERT)
    check("NEW password works", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    print("=== STEP 10: reset-token reuse is rejected ===")
    r = requests.post(f"{ORIGIN}/api/auth/reset-password", json={"newPassword": "AnotherPassword78!", "token": reset_token}, headers=headers, verify=CA_CERT)
    check_rejected("reusing the same (already-consumed) reset token is rejected", r)

    print("=== STEP 11: fabricated reset token is rejected ===")
    r = requests.post(f"{ORIGIN}/api/auth/reset-password", json={"newPassword": "AnotherPassword90!", "token": "fabricated-" + rand_suffix()}, headers=headers, verify=CA_CERT)
    check_rejected("fabricated reset token is rejected", r)

    print()
    if FAILED:
        print("RESULT: one or more checks FAILED")
        return 1
    print("RESULT: all checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
