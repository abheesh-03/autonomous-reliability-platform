"""Best-effort bounding/redaction for free-text fields copied from
control-plane's incident response, before they enter durable LangGraph
graph state (Phase 7 correction round, finding #4).

V1's `reliability.incidents` schema imposes no length bound on
`title`/`description` (see
database/migrations/V1__create_incident_schema.sql), and they are free
text written by whatever upstream produced the incident (an
Alertmanager annotation, a human operator's own text). Phase 7's own
requirement is that any external text placed into persisted state
already obeys the bounding/redaction guarantees Phases 5/6 established
for investigator-service's own evidence text (see
investigator_service.redaction and investigator_service.config's
`INVESTIGATOR_MAX_INCIDENT_TEXT_LENGTH`) -- this module is this
service's own small, independently-tested equivalent, not an import of
investigator-service's internals: these are separate deployables, and
importing another service's module as a runtime dependency just to
reuse one helper would create exactly the kind of coupling this
platform's by-hand-mirrored-domain-model convention deliberately
avoids elsewhere (see domain/incident_snapshot.py's own docstring).

Stated honestly, same as investigator_service.redaction's own
docstring: this is a reasonable, documented safety margin against the
most common accidental-leak shapes, NOT a guarantee that no
secret-shaped text can ever appear in persisted state.

Phase 7 correction round (follow-up), finding #2: `source` and
`source_fingerprint` are ALSO externally-derived free text -- the
control-plane/Alertmanager model requires `source_fingerprint` to be
non-empty but imposes no maximum length, and an independent review
reproduced a 5000+ character, credential-shaped fingerprint being
persisted completely untouched. Both are now bounded/redacted exactly
like `title`/`description`. Deliberately NOT touched: `id` (UUID),
`status`/`severity` (closed enums), and the four timestamp fields --
none of those are free text, and truncating/redacting a UUID or an
enum value would silently corrupt it rather than protect anything.
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

# Only the incident's OWN known free-text fields are bounded/redacted
# here -- a targeted, auditable allowlist, never a generic deep-walk
# over arbitrary dict keys (which would risk silently mangling a
# structured field like `id`/`status` that must never be truncated).
_BOUNDED_TEXT_FIELDS = ("title", "description", "source", "source_fingerprint")

_TRUNCATION_SUFFIX = "...[truncated]"


def hard_bound(text: str, max_chars: int, *, suffix: str = _TRUNCATION_SUFFIX) -> str:
    """Truncates `text` so the ENTIRE returned string -- INCLUDING
    `suffix`, when truncation actually happens -- never exceeds
    `max_chars`. Phase 7 correction round (follow-up), finding #1: a
    prior version appended the suffix AFTER already slicing to
    `max_chars`, so the real returned length could exceed the
    configured maximum by `len(suffix)` characters (independently
    reproduced: `max_chars=2000` produced a 2014-character string).

    Defensive-only edge case: if `max_chars` is somehow not even large
    enough to hold `suffix` (never true for this service's own clamped
    config -- `AGENT_RUNTIME_MAX_INCIDENT_TEXT_LENGTH`'s minimum is
    100, `AGENT_RUNTIME_MAX_ERROR_DETAIL_CHARS`'s is 50, both well
    above `len(suffix)`), the suffix is dropped entirely rather than
    ever exceeding `max_chars`.
    """
    if len(text) <= max_chars:
        return text
    if max_chars <= len(suffix):
        return text[:max_chars]
    return text[: max_chars - len(suffix)] + suffix


def _redact(text: str) -> str:
    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _bound_and_redact_text(text: str, max_chars: int) -> str:
    return hard_bound(_redact(text), max_chars)


def bound_and_redact(incident_snapshot: dict, *, max_text_chars: int) -> dict:
    """Returns a NEW dict (never mutates `incident_snapshot`) with every
    field named in `_BOUNDED_TEXT_FIELDS` bounded to `max_text_chars`
    (a real hard bound -- see `hard_bound`) and passed through the
    redaction patterns above. A missing or non-string value (e.g.
    `description: None`) passes through unchanged -- this function
    only ever touches real text, never a UUID, enum, or timestamp."""
    bounded = dict(incident_snapshot)
    for field in _BOUNDED_TEXT_FIELDS:
        value = bounded.get(field)
        if isinstance(value, str):
            bounded[field] = _bound_and_redact_text(value, max_text_chars)
    return bounded
