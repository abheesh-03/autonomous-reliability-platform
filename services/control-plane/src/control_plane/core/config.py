"""Database connection settings, read from individual environment
variables — never a single pre-built connection string. This matters:
a manually concatenated "postgresql://user:password@host/db" string
breaks if the password contains characters like "@", "/", or "#", and
credentials must never appear as a source-code constant. Each
component is read separately here and handed to SQLAlchemy's
URL.create() (see db/engine.py), which percent-encodes every component
correctly.
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("control_plane.config")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    user: str
    password: str
    database: str
    pool_size: int
    pool_pre_ping: bool
    pool_timeout_seconds: float
    connect_timeout_seconds: float
    command_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        return cls(
            # "postgres" is this Compose project's internal DNS name
            # for the existing PostgreSQL service (see
            # docker-compose.yml); the internal port is always 5432
            # regardless of whatever host port POSTGRES_PORT maps to
            # for external access, so it is intentionally not reused
            # here.
            host=os.environ.get("POSTGRES_HOST", "postgres"),
            port=int(os.environ.get("POSTGRES_INTERNAL_PORT", "5432")),
            user=_require_env("POSTGRES_USER"),
            password=_require_env("POSTGRES_PASSWORD"),
            database=_require_env("POSTGRES_DB"),
            pool_size=int(os.environ.get("CONTROL_PLANE_DB_POOL_SIZE", "5")),
            pool_pre_ping=True,
            pool_timeout_seconds=float(os.environ.get("CONTROL_PLANE_DB_POOL_TIMEOUT_SECONDS", "5")),
            connect_timeout_seconds=float(os.environ.get("CONTROL_PLANE_DB_CONNECT_TIMEOUT_SECONDS", "5")),
            command_timeout_seconds=float(os.environ.get("CONTROL_PLANE_DB_COMMAND_TIMEOUT_SECONDS", "10")),
        )


@dataclass(frozen=True)
class WebhookSettings:
    """Phase 3C: the shared secret the Alertmanager -> control-plane
    webhook (api/webhook_auth.py) checks incoming Bearer tokens
    against. Deliberately NOT required at startup the way the database
    settings are: an unconfigured token must not crash this
    service's read-only API (see docs/api/control-plane.md) — instead
    it makes every webhook request fail closed (401), since
    `token` is None and no supplied value can ever equal it. The same
    value is generated and mirrored into
    observability/alertmanager/secrets/webhook-token by
    scripts/init-webhook-secret.sh.
    """

    token: str | None

    @classmethod
    def from_env(cls) -> "WebhookSettings":
        raw = os.environ.get("CONTROL_PLANE_WEBHOOK_TOKEN", "")
        return cls(token=raw if raw.strip() else None)


@dataclass(frozen=True)
class LifecycleSettings:
    """Phase 3D: the shared secret the human/operator lifecycle
    endpoint (PATCH /api/v1/incidents/{id}/status, api/auth.py's
    require_lifecycle_token) checks incoming Bearer tokens against.

    Deliberately a SEPARATE environment variable and a SEPARATE
    app.state attribute from WebhookSettings above — never the same
    value. Alertmanager is only ever given the webhook token (see
    observability/alertmanager/secrets/webhook-token); it has no way to
    learn this one, so it cannot invoke the lifecycle endpoint, by
    construction, not merely by convention.

    Same non-blocking-startup philosophy as WebhookSettings: an
    unconfigured token must not crash this service — it just makes
    every lifecycle request fail closed (401), since `token` is None
    and no supplied value can ever equal it. Generated and kept in
    sync by the same scripts/init-webhook-secret.sh that handles the
    webhook token, but — unlike it — never mirrored into any file
    Alertmanager (or anything else) can read; it reaches this service
    purely as an environment variable.
    """

    token: str | None

    @classmethod
    def from_env(cls) -> "LifecycleSettings":
        raw = os.environ.get("CONTROL_PLANE_LIFECYCLE_TOKEN", "")
        return cls(token=raw if raw.strip() else None)


@dataclass(frozen=True)
class RemediationTokenSettings:
    """Phase 8: three separate, never-interchangeable Bearer tokens for
    the remediation-proposal domain. Same non-blocking-startup
    philosophy as WebhookSettings/LifecycleSettings — an unconfigured
    token just makes its own endpoint fail closed (401), it never
    crashes this service.

    - `proposal_token` (CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN) — held
      ONLY by agent-runtime-service. Authorizes creating a proposal
      only; cannot approve/reject, cannot record an execution result,
      cannot touch the incident lifecycle endpoint.
    - `approver_token` (CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN) — held
      ONLY by a human/operator (or a CI acceptance script simulating
      one). Never given to agent-runtime-service, tool-gateway,
      investigator-service, or retrieval-service.
    - `executor_token` (CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN) — held
      ONLY by tool-gateway. Authorizes recording execution start/result
      only; cannot create or approve/reject a proposal.
    """

    proposal_token: str | None
    approver_token: str | None
    executor_token: str | None

    @classmethod
    def from_env(cls) -> "RemediationTokenSettings":
        def _opt(name: str) -> str | None:
            raw = os.environ.get(name, "")
            return raw if raw.strip() else None

        return cls(
            proposal_token=_opt("CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN"),
            approver_token=_opt("CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN"),
            executor_token=_opt("CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN"),
        )


def resolve_write_tokens(
    webhook_token: str | None,
    lifecycle_token: str | None,
    remediation_proposal_token: str | None = None,
    remediation_approver_token: str | None = None,
    remediation_executor_token: str | None = None,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Post-review correction: an application-level guard against any
    TWO of this service's write-endpoint tokens being configured
    identically.

    scripts/init-webhook-secret.sh / scripts/init-remediation-secrets.sh
    refuse to produce such a combination in the first place — but
    nothing stops an operator from hand-editing .env, or setting these
    environment variables directly in some other deployment mechanism,
    bypassing both scripts entirely. If that happens, the whole reason
    these are separate credentials — Alertmanager must never invoke the
    human/operator lifecycle endpoint; agent-runtime-service must never
    approve/reject or record an execution result; tool-gateway must
    never create or approve a proposal; a human approver's credential
    must never double as anything an automated service could present —
    is silently defeated: a single leaked/observed token would then
    authorize more than one write path. This function is called once,
    at startup (main.py's lifespan), after every token is independently
    read from the environment, and is deliberately a plain function
    (not reaching into app.state itself) so it is directly unit-testable
    without constructing the whole FastAPI app.

    For every PAIR of the five tokens that are both configured
    (non-None) and equal, BOTH members of that pair are returned as
    None — i.e. every endpoint either of them would authorize fails
    closed, exactly as if neither token had ever been configured —
    rather than letting either authorize the other's endpoint(s). This
    does not crash the process (consistent with the non-blocking-startup
    philosophy every other setting in this module already follows): a
    misconfigured secret must not take down the read-only API. Every
    misconfiguration is logged as an error server-side by NAME only;
    no token value is ever logged.

    A token being unconfigured (None) is unaffected by this check for
    any pair it is not part of, and continues to fail closed only for
    its own endpoint(s), same as before this function existed.
    """
    names = (
        "CONTROL_PLANE_WEBHOOK_TOKEN",
        "CONTROL_PLANE_LIFECYCLE_TOKEN",
        "CONTROL_PLANE_REMEDIATION_PROPOSAL_TOKEN",
        "CONTROL_PLANE_REMEDIATION_APPROVER_TOKEN",
        "CONTROL_PLANE_REMEDIATION_EXECUTOR_TOKEN",
    )
    values = [
        webhook_token,
        lifecycle_token,
        remediation_proposal_token,
        remediation_approver_token,
        remediation_executor_token,
    ]
    cleared = [False] * len(values)
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if values[i] is not None and values[j] is not None and values[i] == values[j]:
                logger.error(
                    "%s and %s are configured identically — every endpoint either one would "
                    "authorize will fail closed until they are set to two different values",
                    names[i],
                    names[j],
                )
                cleared[i] = True
                cleared[j] = True

    resolved = [None if cleared[i] else values[i] for i in range(len(values))]
    return tuple(resolved)  # type: ignore[return-value]
