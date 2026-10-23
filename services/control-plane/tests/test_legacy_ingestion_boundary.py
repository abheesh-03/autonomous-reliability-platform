"""Phase 14 correction round, Issue 4: proves the explicit boundary
between legacy, non-tenant-aware ingestion and secure/multi-tenant
mode -- see core/config.py::LegacyIngestionSettings and
core/authz.py::require_legacy_ingestion_allowed.
"""

from datetime import UTC, datetime

import pytest

from control_plane.core.config import LegacyIngestionSettings, OrganizationContextSettings
from control_plane.main import app
from tests.conftest import KUBERNETES_INGESTION_TOKEN, WEBHOOK_TOKEN

WEBHOOK_URL = "/internal/v1/alertmanager/webhook"
WEBHOOK_AUTH = {"Authorization": f"Bearer {WEBHOOK_TOKEN}"}


def _webhook_payload() -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "version": "4",
        "groupKey": "{}:{alertname=...}",
        "status": "firing",
        "receiver": "control-plane-webhook",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "TelemetryPipelineUnavailable", "severity": "critical"},
                "annotations": {"summary": "s", "description": "d"},
                "startsAt": now,
                "fingerprint": "fp-legacy-ingestion-boundary",
            }
        ],
    }


@pytest.fixture
def org_context_enabled(client):
    previous = app.state.organization_context_settings
    app.state.organization_context_settings = OrganizationContextSettings(enabled=True)
    yield client
    app.state.organization_context_settings = previous


@pytest.fixture
def legacy_ingestion(request):
    """Parametrized via request.param: True/False for
    allow_legacy_ingestion."""
    previous = app.state.legacy_ingestion_settings
    app.state.legacy_ingestion_settings = LegacyIngestionSettings(allow_legacy_ingestion=request.param)
    yield
    app.state.legacy_ingestion_settings = previous


def test_legacy_webhook_ingestion_works_by_default_when_org_context_disabled(use_repository, client):
    # The pre-Phase-14 default -- org context OFF entirely -- is
    # completely unaffected by this correction round.
    use_repository([])
    response = client.post(WEBHOOK_URL, headers=WEBHOOK_AUTH, json=_webhook_payload())
    assert response.status_code == 200


@pytest.mark.parametrize("legacy_ingestion", [True], indirect=True)
def test_legacy_webhook_ingestion_still_works_in_secure_mode_by_default(
    use_repository, org_context_enabled, legacy_ingestion
):
    # Secure mode ON, but CONTROL_PLANE_ALLOW_LEGACY_INGESTION defaults
    # true -- existing CI/local-dev ingestion scripts keep working
    # even once an operator turns on organization-context enforcement
    # for everything else.
    use_repository([])
    response = org_context_enabled.post(WEBHOOK_URL, headers=WEBHOOK_AUTH, json=_webhook_payload())
    assert response.status_code == 200


@pytest.mark.parametrize("legacy_ingestion", [False], indirect=True)
def test_legacy_webhook_ingestion_fails_closed_when_explicitly_disabled(
    use_repository, org_context_enabled, legacy_ingestion
):
    repo = use_repository([])
    response = org_context_enabled.post(WEBHOOK_URL, headers=WEBHOOK_AUTH, json=_webhook_payload())
    assert response.status_code == 503
    # No mutation occurred -- the real token check already passed
    # (this is additive, not a replacement), but the request was still
    # rejected before reaching the repository.
    assert len(repo.rows) == 0


@pytest.mark.parametrize("legacy_ingestion", [False], indirect=True)
def test_kubernetes_ingestion_also_fails_closed_when_legacy_ingestion_is_disabled(
    use_repository, org_context_enabled, legacy_ingestion
):
    use_repository([])
    response = org_context_enabled.post(
        "/internal/v1/kubernetes/findings",
        headers={"Authorization": f"Bearer {KUBERNETES_INGESTION_TOKEN}"},
        json={
            "cluster": "kind-reliability-lab",
            "namespace": "reliability-sandbox",
            "resource_kind": "Deployment",
            "resource_name": "crashloop-demo",
            "resource_uid": "11111111-1111-1111-1111-111111111111",
            "detector_id": "crashloop_backoff",
            "result": "detected",
            "severity": "critical",
            "title": "t",
            "description": "d",
            "collection_completeness": "complete",
            "collected_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 503
