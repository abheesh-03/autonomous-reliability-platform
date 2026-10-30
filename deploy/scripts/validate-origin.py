#!/usr/bin/env python3
"""Phase 17A correction round: real HTTPS-origin validation for
deploy/scripts/preflight.sh.

The prior round's check was a bare shell `case` glob
(`https://*` matches ANY string starting with those 8 characters,
including just "https://" with an empty hostname -- confirmed by
independent fault injection to pass with
DEPLOYMENT_PUBLIC_ORIGIN="https://"). This uses Python's own
`urllib.parse` (never a hand-rolled regex) to require: scheme
exactly "https", a real, non-empty hostname, no userinfo
(username/password), no path other than "" or "/", no query, no
fragment, and -- if a port is present -- a syntactically valid one
(urlsplit itself raises ValueError on a malformed port, caught
below).

Usage: validate-origin.py <origin>
Exit 0 if valid, 1 otherwise, with a one-line reason on stderr. Never
prints anything but the input it was given back (the origin itself is
not a secret).
"""

import sys
from urllib.parse import urlsplit


def fail(reason: str) -> None:
    print(f"INVALID: {reason}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: validate-origin.py <origin>")
    origin = sys.argv[1]

    try:
        parsed = urlsplit(origin)
    except ValueError as exc:
        fail(f"could not parse as a URL: {exc}")
        return

    if parsed.scheme != "https":
        fail(f"scheme must be exactly 'https' (got {parsed.scheme!r})")

    try:
        hostname = parsed.hostname
    except ValueError as exc:
        fail(f"could not extract hostname: {exc}")
        return
    if not hostname:
        fail("hostname is empty")

    try:
        port = parsed.port
    except ValueError as exc:
        fail(f"invalid port: {exc}")
        return
    if port is not None and not (1 <= port <= 65535):
        fail(f"port out of range: {port}")

    if parsed.username is not None or parsed.password is not None:
        fail("must not contain userinfo (username/password)")

    if parsed.path not in ("", "/"):
        fail(f"must not contain a path (got {parsed.path!r})")

    if parsed.query:
        fail(f"must not contain a query string (got {parsed.query!r})")

    if parsed.fragment:
        fail(f"must not contain a fragment (got {parsed.fragment!r})")

    print(f"VALID: scheme=https hostname={hostname!r} port={port}")
    sys.exit(0)


if __name__ == "__main__":
    main()
