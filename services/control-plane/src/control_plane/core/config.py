"""Database connection settings, read from individual environment
variables — never a single pre-built connection string. This matters:
a manually concatenated "postgresql://user:password@host/db" string
breaks if the password contains characters like "@", "/", or "#", and
credentials must never appear as a source-code constant. Each
component is read separately here and handed to SQLAlchemy's
URL.create() (see db/engine.py), which percent-encodes every component
correctly.
"""

import os
from dataclasses import dataclass


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
