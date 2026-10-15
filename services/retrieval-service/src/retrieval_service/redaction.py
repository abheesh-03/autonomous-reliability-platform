"""Bounded, best-effort redaction of common credential-shaped patterns
from untrusted incident text (title/description, audit metadata)
before it becomes part of a historical-incident retrieval chunk or is
sent to an embedding provider.

This is a separate service/deployable from investigator-service, so
this module is kept consistent BY HAND with
investigator_service/redaction.py rather than shared via code —
same convention investigator_service.domain.incident_snapshot already
documents for its own control-plane response mirrors.

Stated honestly, same as investigator-service's own module: this is
NOT a guarantee that no secret can ever appear in indexed text -- a
reasonable, documented safety margin only. See
docs/architecture/phase-6-rag-retrieval.md.
"""

import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[a-z0-9\-_.=]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\bauthorization\s*:\s*[^\n]+"), "Authorization: [REDACTED]"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY_ID]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
)


def redact(text: str) -> str:
    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
