"""Shared test fixtures. Unit tests never make a real network call or
a real database connection -- see individual test modules for which
seam each fake double replaces (the same philosophy
investigator-service's and control-plane's own test suites use).

Real PostgreSQL+pgvector/HTTP integration behavior (constraints,
idempotent upserts, cosine-distance ranking against real data, the
real indexer against a real control-plane) is covered by
scripts/verify-rag.sh against the real Compose stack, not here.
"""

import uuid

SAMPLE_INCIDENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
