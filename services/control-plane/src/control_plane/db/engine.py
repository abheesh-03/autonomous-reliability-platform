"""Async SQLAlchemy engine construction.

Critical property, relied on throughout this service (see
docs/architecture/system-overview.md and
docs/api/control-plane.md, "Startup and migration ordering"):
`create_async_engine()` does NOT open a connection at construction
time — it only prepares the engine and its connection pool. This is
required because the existing `flyway` Compose service is gated behind
`profiles: ["tools"]` and does not run automatically, so
`reliability.incidents` may not exist yet (or PostgreSQL may not even
be reachable yet) when this process starts. Constructing the engine
must succeed regardless; only an actual query attempt can fail, and
only then.
"""

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from control_plane.core.config import DatabaseSettings


def build_database_url(settings: DatabaseSettings) -> URL:
    # URL.create() percent-encodes every component safely — unlike an
    # f-string/manual concatenation, a password containing "@", "/", or
    # "#" cannot corrupt the resulting URL.
    return URL.create(
        drivername="postgresql+asyncpg",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
    )


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    return create_async_engine(
        build_database_url(settings),
        # Connection pooling with stale-connection detection: a
        # connection that has gone bad (e.g. PostgreSQL restarted,
        # dropping existing TCP connections) is detected with a
        # lightweight liveness check before being handed out, rather
        # than failing the request with a stale-connection error.
        pool_pre_ping=settings.pool_pre_ping,
        pool_size=settings.pool_size,
        # Bounded wait for a pooled connection, and bounded connect/
        # command timeouts passed straight to asyncpg — a request can
        # never hang indefinitely on a slow or unreachable database.
        pool_timeout=settings.pool_timeout_seconds,
        connect_args={
            "timeout": settings.connect_timeout_seconds,
            "command_timeout": settings.command_timeout_seconds,
        },
    )
