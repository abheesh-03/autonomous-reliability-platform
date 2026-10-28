"""Phase 16 Gate 3: integration-credential generation/verification.

Mirrors the same shape real API-credential systems (Stripe, GitHub,
Linear) use: a public, non-secret, indexed LOOKUP id, plus a private
SECRET portion that is never stored in recoverable form -- only a
SHA-256 digest of it. A SHA-256 digest (not bcrypt/argon2) is the
correct choice here specifically because the secret is a 256-bit
CSPRNG-generated token, not a human-chosen password: it already has
far more entropy than any realistic offline dictionary/brute-force
attack could search, so the slow key-stretching bcrypt/argon2 exist for
(defending a LOW-entropy human password against guessing) buys nothing
here and would only add needless latency to every ingestion request.
`hmac.compare_digest` is used for the actual comparison, never `==`,
to avoid a timing side-channel on the stored digest.
"""

import hashlib
import hmac
import secrets

# "cred_" + 22 URL-safe base64 characters (~132 bits of entropy) -- the
# PUBLIC lookup id. Never secret by itself; knowing it alone grants
# nothing (see verify_secret below). Short enough to display/copy
# comfortably, long enough that it is never practically guessable or
# enumerable.
_CREDENTIAL_ID_PREFIX = "cred_"
_CREDENTIAL_ID_RANDOM_BYTES = 16  # -> 22 base64 chars

# The PRIVATE secret portion -- 256 bits of real CSPRNG entropy,
# `secrets.token_urlsafe` (Python's own CSPRNG, documented as
# suitable for security-sensitive tokens). Shown to the caller exactly
# once, at creation time; never persisted or logged anywhere in
# recoverable form.
_SECRET_RANDOM_BYTES = 32


def generate_credential_id() -> str:
    return _CREDENTIAL_ID_PREFIX + secrets.token_urlsafe(_CREDENTIAL_ID_RANDOM_BYTES)


def generate_secret() -> str:
    return secrets.token_urlsafe(_SECRET_RANDOM_BYTES)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, expected_hash: str) -> bool:
    """Constant-time comparison -- never a plain `==` against the
    stored hash, which would leak timing information about how many
    leading hex characters matched."""
    return hmac.compare_digest(hash_secret(secret), expected_hash)


def format_bearer_token(credential_id: str, secret: str) -> str:
    """The exact string shown to the user once, and the exact string a
    real client sends as `Authorization: Bearer <this>`."""
    return f"{credential_id}.{secret}"


def parse_bearer_token(token: str) -> tuple[str, str] | None:
    """Splits `<credential_id>.<secret>` -- returns None (never raises)
    for anything structurally invalid, so a caller can treat a
    malformed token identically to an unrecognized one (401, not 500)."""
    if "." not in token:
        return None
    credential_id, _, secret = token.partition(".")
    if not credential_id.startswith(_CREDENTIAL_ID_PREFIX) or not secret:
        return None
    return credential_id, secret
