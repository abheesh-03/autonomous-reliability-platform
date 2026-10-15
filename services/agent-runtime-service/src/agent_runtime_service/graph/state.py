"""The explicit, typed LangGraph state (Phase 7 §GRAPH STATE).

Every field here is bounded, JSON-serializable workflow data -- never
a Python client object, an API key, a Bearer token, a database
password, an Authorization header, raw SDK exception text, an HTTP
client, a database connection, or a subprocess handle. The only
"heavy" nested values (`incident_snapshot`, `investigation_report`)
are plain dicts produced by `model_dump(mode="json")` on this
service's own, already-validated domain mirrors
(domain/incident_snapshot.py, domain/investigation.py).

`incident_snapshot` comes from control-plane, whose `reliability.incidents`
schema imposes no length bound on `title`/`description`/`source`/
`source_fingerprint` at all, so `graph/nodes.py::load_incident` passes
it through `text_safety.bound_and_redact` (Phase 7 correction round,
findings #4 and follow-up #2) before it ever reaches this state --
never persisted as raw, unbounded, unredacted wire text just because
control-plane returned it that way. (`id`/`status`/`severity`/the
timestamp fields are left untouched -- they are not free text.)

`investigation_report` carries through text investigator-service
already bounded/redacted per Phase 5/6's own guarantees for each
INDIVIDUAL field -- this module never re-renders or re-collects
evidence text itself. Phase 5/6 impose no ceiling on the report AS A
WHOLE, however, so `graph/nodes.py::run_investigation` additionally
enforces its own hard ceiling on the report's total SERIALIZED SIZE
(`RuntimeBounds.max_investigation_report_bytes`, correction round
follow-up finding #3) before persisting it here -- an oversized
report is rejected (`error_code="investigator_output_too_large"`) and
never enters this field at all, rather than being persisted
unbounded.

`completed_nodes` uses LangGraph's standard `operator.add` reducer so
each node's own return value (`{"completed_nodes": ["this_node"]}`)
APPENDS rather than replaces -- confirmed empirically against a real
checkpoint store before this was adopted (see
docs/architecture/phase-7-durable-agent-runtime.md). Every other field
uses the default "last write wins" channel (a node that doesn't touch
a field simply leaves it unchanged).

`attempt_counts` is deliberately NOT a persisted field. Phase 7's
original design note reasoned this was always recoverable from
checkpoint history alone -- corrected (Phase 7 correction round,
finding #11): that is only true for a node whose own output checkpoint
was successfully committed. A node that crashes or hits a transient,
uncaught dependency failure (see graph/nodes.py's own TERMINAL vs
TRANSIENT/RETRYABLE split) may have actually executed -- calling the
real external dependency one or more times -- WITHOUT ever leaving
behind a corresponding "this node completed" checkpoint entry, so
checkpoint history is not a complete, exact attempt counter in
general; it only ever undercounts, never overcounts. `attempt_counts`
is still correctly omitted here, but for a narrower, honest reason: no
Phase 7 behavior actually depends on an exact count (retries are
caller-driven via `resume`, not internally bounded), so there is
nothing for a counter to guard yet -- not because the count is already
fully recoverable elsewhere.
"""

import operator
from typing import Annotated, TypedDict


class AgentGraphState(TypedDict, total=False):
    run_id: str
    incident_id: str
    status: str  # "running" | "completed" | "failed"
    started_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    completed_at: str | None

    current_node: str
    completed_nodes: Annotated[list[str], operator.add]

    incident_snapshot: dict | None
    investigation_report: dict | None
    result_quality: str | None  # "well_supported" | "inconclusive" | "partial"
    validation_notes: list[str]

    error_code: str | None
    error_detail: str | None
