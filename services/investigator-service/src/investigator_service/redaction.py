"""Bounded, best-effort redaction of common credential-shaped patterns
from untrusted evidence text (log lines, incident title/description)
before it becomes part of the evidence package the model sees.

Stated honestly (Phase 5 correction round #7): this is NOT a guarantee
that no secret can ever appear in evidence text — it is a reasonable,
documented safety margin against the most common accidental-leak
shapes this platform's own real logs could plausibly contain (a
`Bearer`/`Authorization` value, an inline `api_key=`/`password=`
assignment, a handful of well-known API-key prefixes). A sufficiently
unusual or obfuscated secret could still pass through unredacted. See
docs/architecture/phase-5-ai-investigator.md's security section.
"""

import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[a-z0-9\-_.=]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\bauthorization\s*:\s*[^\n]+"), "Authorization: [REDACTED]"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    # AWS-style access key ID.
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY_ID]"),
    # OpenAI-style secret key.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
)


def redact(text: str) -> str:
    """Applies every pattern in sequence. Cheap and bounded — intended
    to run on already-length-capped evidence text (log lines, incident
    text), never on an unbounded blob."""
    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
