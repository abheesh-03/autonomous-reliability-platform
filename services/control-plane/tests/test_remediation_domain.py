"""Phase 8 correction round (finding #6): V6's own migration comments
document that each individual evidence/context id is bounded to
MAX_ID_CHARS (200) in application code -- these tests prove that claim
is actually true at the Pydantic layer, not merely at the (list-length-
only) `max_length` that previously existed.
"""

import uuid

import pytest
from pydantic import ValidationError

from control_plane.domain.remediation import MAX_ID_CHARS, MAX_IDS_JOINED_CHARS, RemediationProposalCreateRequest


def _base_kwargs(**overrides) -> dict:
    kwargs = dict(
        incident_id=uuid.uuid4(),
        agent_run_id=uuid.uuid4(),
        idempotency_key=f"phase8-proposal:{uuid.uuid4()}",
        action_type="clear_payment_authorization_fault",
        target="payment-service",
        reason="test reason",
        supporting_evidence_ids=[],
        supporting_context_ids=[],
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------
# Phase 12B-D (Gate 5): action_type/target/target_cluster pair
# validation -- never a cross-product, mirrors V7's own combined CHECK
# constraint at the application layer.
# ---------------------------------------------------------------------


def test_valid_payment_pair_is_accepted():
    request = RemediationProposalCreateRequest(**_base_kwargs())
    assert request.target_cluster is None
    assert request.expected_resource_uid is None


def test_valid_kubernetes_pair_is_accepted():
    request = RemediationProposalCreateRequest(
        **_base_kwargs(
            action_type="restart_allowlisted_deployment",
            target="Deployment/reliability-sandbox/crashloop-demo",
            target_cluster="kind-reliability-lab",
            expected_resource_uid="uid-123",
        )
    )
    assert request.target_cluster == "kind-reliability-lab"


def test_kubernetes_action_against_payment_target_is_denied():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(
            **_base_kwargs(
                action_type="restart_allowlisted_deployment",
                target="payment-service",
                target_cluster="kind-reliability-lab",
                expected_resource_uid="uid-123",
            )
        )


def test_payment_action_against_kubernetes_target_is_denied():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(
            **_base_kwargs(action_type="clear_payment_authorization_fault", target="Deployment/reliability-sandbox/crashloop-demo")
        )


def test_kubernetes_action_missing_expected_resource_uid_is_denied():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(
            **_base_kwargs(
                action_type="restart_allowlisted_deployment",
                target="Deployment/reliability-sandbox/crashloop-demo",
                target_cluster="kind-reliability-lab",
            )
        )


def test_payment_action_with_a_target_cluster_set_is_denied():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(**_base_kwargs(target_cluster="kind-reliability-lab"))


def test_unsupported_deployment_target_is_denied():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(
            **_base_kwargs(
                action_type="restart_allowlisted_deployment",
                target="Deployment/reliability-sandbox/some-other-deployment",
                target_cluster="kind-reliability-lab",
                expected_resource_uid="uid-123",
            )
        )


def test_unsupported_namespace_is_denied():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(
            **_base_kwargs(
                action_type="restart_allowlisted_deployment",
                target="Deployment/other-namespace/crashloop-demo",
                target_cluster="kind-reliability-lab",
                expected_resource_uid="uid-123",
            )
        )


def test_unsupported_cluster_is_denied():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(
            **_base_kwargs(
                action_type="restart_allowlisted_deployment",
                target="Deployment/reliability-sandbox/crashloop-demo",
                target_cluster="some-other-cluster",
                expected_resource_uid="uid-123",
            )
        )


def test_evidence_id_at_exactly_the_bound_is_accepted():
    request = RemediationProposalCreateRequest(**_base_kwargs(supporting_evidence_ids=["e" * MAX_ID_CHARS]))
    assert len(request.supporting_evidence_ids[0]) == MAX_ID_CHARS


def test_evidence_id_one_char_over_the_bound_is_rejected():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(**_base_kwargs(supporting_evidence_ids=["e" * (MAX_ID_CHARS + 1)]))


def test_context_id_at_exactly_the_bound_is_accepted():
    request = RemediationProposalCreateRequest(**_base_kwargs(supporting_context_ids=["c" * MAX_ID_CHARS]))
    assert len(request.supporting_context_ids[0]) == MAX_ID_CHARS


def test_context_id_one_char_over_the_bound_is_rejected():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(**_base_kwargs(supporting_context_ids=["c" * (MAX_ID_CHARS + 1)]))


def test_empty_evidence_id_is_rejected():
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(**_base_kwargs(supporting_evidence_ids=[""]))


def _ids_totaling_joined_length(total_chars: int) -> list[str]:
    """Builds a list of <=200-char, non-empty ids whose
    `len(",".join(ids))` is EXACTLY `total_chars` -- mirrors
    PostgreSQL's own `array_to_string(ids, ',')` semantics exactly
    (Phase 8 correction round, finding #5 second pass). 24 ids of 200
    chars + one remainder id, joined by 24 commas."""
    ids = ["e" * MAX_ID_CHARS for _ in range(24)]
    commas = len(ids)  # one more id follows, so this many commas total
    remainder = total_chars - sum(len(i) for i in ids) - commas
    assert 1 <= remainder <= MAX_ID_CHARS, f"remainder {remainder} out of range for this helper"
    ids.append("r" * remainder)
    assert len(",".join(ids)) == total_chars
    return ids


def test_evidence_ids_joined_length_at_exactly_the_aggregate_bound_is_accepted():
    ids = _ids_totaling_joined_length(MAX_IDS_JOINED_CHARS)
    request = RemediationProposalCreateRequest(**_base_kwargs(supporting_evidence_ids=ids))
    assert len(",".join(request.supporting_evidence_ids)) == MAX_IDS_JOINED_CHARS


def test_evidence_ids_joined_length_one_char_over_the_aggregate_bound_is_rejected():
    ids = _ids_totaling_joined_length(MAX_IDS_JOINED_CHARS + 1)
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(**_base_kwargs(supporting_evidence_ids=ids))


def test_context_ids_joined_length_one_char_over_the_aggregate_bound_is_rejected():
    ids = _ids_totaling_joined_length(MAX_IDS_JOINED_CHARS + 1)
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(**_base_kwargs(supporting_context_ids=ids))


def test_many_small_ids_under_element_cap_but_over_aggregate_bound_is_rejected():
    """The exact scenario the correction round's own finding describes:
    many 200-char ids whose per-element and per-list-length checks
    both individually pass (<=50 elements, each <=200 chars) but whose
    JOINED total exceeds 5000 -- previously only caught as a PostgreSQL
    CHECK violation; now caught here first."""
    ids = ["e" * MAX_ID_CHARS for _ in range(30)]  # 30 <= 50, each == 200
    assert len(",".join(ids)) > MAX_IDS_JOINED_CHARS
    with pytest.raises(ValidationError):
        RemediationProposalCreateRequest(**_base_kwargs(supporting_evidence_ids=ids))
