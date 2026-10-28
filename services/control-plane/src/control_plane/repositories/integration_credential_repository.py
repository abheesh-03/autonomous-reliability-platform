"""Database access for reliability.integration_credentials (Phase 16
Gate 2/3). Same bare `sa.table()`/`sa.column()` Core-table convention
every other repository in this service already uses.
"""

import datetime
import uuid
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

integration_credentials_table = sa.table(
    "integration_credentials",
    sa.column("id", PG_UUID(as_uuid=True)),
    sa.column("organization_id", PG_UUID(as_uuid=True)),
    sa.column("service_id", PG_UUID(as_uuid=True)),
    sa.column("connection_type"),
    sa.column("credential_id"),
    sa.column("credential_secret_hash"),
    sa.column("status"),
    sa.column("created_by_user_id"),
    sa.column("created_at"),
    sa.column("updated_at"),
    sa.column("revoked_at"),
    sa.column("last_verified_telemetry_at"),
    schema="reliability",
)


class IntegrationCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        organization_id: uuid.UUID | str,
        service_id: uuid.UUID | str,
        connection_type: str,
        credential_id: str,
        credential_secret_hash: str,
        created_by_user_id: str,
    ) -> Mapping:
        stmt = (
            sa.insert(integration_credentials_table)
            .values(
                organization_id=str(organization_id),
                service_id=str(service_id),
                connection_type=connection_type,
                credential_id=credential_id,
                credential_secret_hash=credential_secret_hash,
                status="active",
                created_by_user_id=created_by_user_id,
            )
            .returning(integration_credentials_table)
        )
        result = await self._session.execute(stmt)
        row = result.mappings().first()
        assert row is not None
        await self._session.commit()
        return row

    async def list_for_service(self, organization_id: uuid.UUID | str, service_id: uuid.UUID | str) -> Sequence[Mapping]:
        # Gate 2: "a service belongs to exactly one organization" --
        # scoped by BOTH organization_id and service_id, never
        # service_id alone (a service_id from another organization must
        # never leak a result here, even if somehow guessed).
        stmt = (
            sa.select(integration_credentials_table)
            .where(
                integration_credentials_table.c.organization_id == str(organization_id),
                integration_credentials_table.c.service_id == str(service_id),
            )
            .order_by(integration_credentials_table.c.created_at.desc())
        )
        return (await self._session.execute(stmt)).mappings().all()

    async def get_by_credential_id(self, credential_id: str) -> Mapping | None:
        """The ingestion hot path's own lookup -- by the PUBLIC,
        non-secret id only. The caller must still verify the secret's
        hash (core/credentials.py::verify_secret) before trusting
        anything this returns; finding a row here proves nothing by
        itself."""
        stmt = sa.select(integration_credentials_table).where(
            integration_credentials_table.c.credential_id == credential_id
        )
        return (await self._session.execute(stmt)).mappings().first()

    async def get_by_id_for_organization(
        self, organization_id: uuid.UUID | str, integration_id: uuid.UUID | str
    ) -> Mapping | None:
        stmt = sa.select(integration_credentials_table).where(
            integration_credentials_table.c.id == str(integration_id),
            integration_credentials_table.c.organization_id == str(organization_id),
        )
        return (await self._session.execute(stmt)).mappings().first()

    async def revoke(self, integration_id: uuid.UUID | str) -> Mapping | None:
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            sa.update(integration_credentials_table)
            .where(integration_credentials_table.c.id == str(integration_id))
            .values(status="revoked", revoked_at=now, updated_at=now)
            .returning(integration_credentials_table)
        )
        result = await self._session.execute(stmt)
        row = result.mappings().first()
        await self._session.commit()
        return row

    async def touch_last_verified_telemetry(self, integration_id: uuid.UUID | str) -> None:
        now = datetime.datetime.now(datetime.UTC)
        stmt = (
            sa.update(integration_credentials_table)
            .where(integration_credentials_table.c.id == str(integration_id))
            .values(last_verified_telemetry_at=now, updated_at=now)
        )
        await self._session.execute(stmt)
        await self._session.commit()
