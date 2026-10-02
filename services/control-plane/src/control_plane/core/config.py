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


def resolve_write_tokens(
    webhook_token: str | None, lifecycle_token: str | None
) -> tuple[str | None, str | None]:
    """Post-review correction: an application-level guard against the
    two write-endpoint tokens (above) being configured identically.

    scripts/init-webhook-secret.sh refuses to produce this combination
    in the first place (see its own "identical token" check) — but
    nothing stops an operator from hand-editing .env, or setting these
    two environment variables directly in some other deployment
    mechanism, bypassing that script entirely. If that happens, the
    whole reason these are two separate credentials — Alertmanager must
    never be able to invoke the human/operator lifecycle endpoint, and
    vice versa — is silently defeated: a single leaked/observed token
    would then authorize both write paths. This function is called
    once, at startup (main.py's lifespan), after both are independently
    read from the environment, and is deliberately a plain function
    (not reaching into app.state itself) so it is directly unit-testable
    without constructing the whole FastAPI app.

    If both are configured (non-None) and equal, BOTH are returned as
    None — i.e. both write endpoints fail closed, exactly as if neither
    token had ever been configured — rather than letting either
    authorize the other's endpoint. This does not crash the process
    (consistent with the non-blocking-startup philosophy every other
    setting in this module already follows): a misconfigured secret
    must not take down the read-only API. The misconfiguration is
    logged as an error server-side; neither token value is ever logged.

    Exactly one token being unconfigured (None) is unaffected by this
    check and continues to fail closed only for its own endpoint, same
    as before this function existed.
    """
    if webhook_token is not None and lifecycle_token is not None and webhook_token == lifecycle_token:
        logger.error(
            "CONTROL_PLANE_WEBHOOK_TOKEN and CONTROL_PLANE_LIFECYCLE_TOKEN are "
            "configured identically — both write endpoints (the Alertmanager "
            "webhook and the human/operator lifecycle PATCH) will fail closed "
            "until they are set to two different values"
        )
        return None, None
    return webhook_token, lifecycle_token
