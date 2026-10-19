"""Gate C: the taxonomy review record. A review entry is evidence FOR
a human to consider -- it is never itself an authoritative correction,
and it never rewrites `ScenarioRecord`. See
`catalog/reviews/audit.py`'s own module docstring for why."""

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ReviewStatus(str, Enum):
    REVIEW_REQUIRED = "review_required"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TaxonomyReviewEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    field_name: str
    original_value: str
    # Only ever a human-authored suggestion once a reviewer has looked
    # at the evidence -- the heuristic itself never fills this in with
    # an invented "correct" value (see audit.py). None until a human
    # provides one.
    suggested_correction: str | None = None
    evidence_rationale: str
    review_status: ReviewStatus = ReviewStatus.REVIEW_REQUIRED
    reviewer: str | None = None
    reviewer_confirmed: bool = False
    heuristic_id: str
