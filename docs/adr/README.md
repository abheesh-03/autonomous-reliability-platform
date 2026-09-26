# Architecture Decision Records (ADRs)

## What is an ADR?

An Architecture Decision Record captures a single significant architectural
or engineering decision: the context that motivated it, the decision
itself, the alternatives that were considered, and the consequences of
making it. ADRs are short, immutable once accepted, and kept alongside the
code so the reasoning behind a decision remains discoverable long after
the decision was made.

## Why this project uses ADRs

This platform will be built incrementally over many phases, likely by
multiple contributors (human and AI) over an extended period. Decisions
made early — such as repository structure, service boundaries, or
technology choices — have long-lasting effects and are easy to
second-guess or accidentally reverse without a record of why they were
made. ADRs give future contributors (including a future version of the
person or agent making the decision) the context needed to either respect
a past decision or deliberately supersede it.

## How future ADRs should be structured

Each ADR lives in `docs/adr/` as `ADR-NNN-short-title.md`, numbered
sequentially, and contains the following sections:

- **Title** — a short descriptive name.
- **Status** — one of `Proposed`, `Accepted`, `Superseded by ADR-NNN`, or
  `Deprecated`.
- **Context** — the problem or forces that made a decision necessary.
- **Decision** — what was decided, stated plainly.
- **Alternatives Considered** — other options that were evaluated and why
  they were not chosen.
- **Consequences** — the resulting tradeoffs, both positive and negative.

ADRs are not updated to reflect new decisions; instead, a new ADR is
written and the old one's status is changed to `Superseded by ADR-NNN`.
This preserves the historical record of what was decided and when.
