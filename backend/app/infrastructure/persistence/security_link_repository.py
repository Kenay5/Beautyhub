"""PostgreSQL lifecycle persistence for administrative security links."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, insert, select, update

from backend.app.application.admin_access.security_links import (
    SecurityLinkStore,
    StoredSecurityLink,
)
from backend.app.domain.authentication.security_link import (
    SecurityLink,
    SecurityLinkPurpose,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    SecurityLink as SecurityLinkModel,
)
from backend.app.infrastructure.persistence.pending_security_state_repository import (
    PostgresPendingSecurityStateStore,
)


class PostgresSecurityLinkStore(SecurityLinkStore):
    """Serialize replacement and conditionally consume one active link."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._pending_state = PostgresPendingSecurityStateStore(connection)

    def replace_active(self, *, link: SecurityLink) -> StoredSecurityLink:
        """Lock the account, retire its prior purpose link and insert the new one."""

        account_id = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(AdminAccount.admin_account_id == link.account_id)
            .with_for_update()
        ).scalar_one_or_none()
        if account_id is None:
            raise ValueError("administrative account is unavailable.")

        expired_rows = self._connection.execute(
            update(SecurityLinkModel)
            .where(
                SecurityLinkModel.admin_account_id == link.account_id,
                SecurityLinkModel.purpose == link.purpose,
                SecurityLinkModel.status == "active",
                SecurityLinkModel.expires_at <= link.issued_at,
            )
            .values(status="expired", updated_at=link.issued_at)
            .returning(
                SecurityLinkModel.admin_account_id,
                SecurityLinkModel.purpose,
            )
        ).all()
        for row in expired_rows:
            self._pending_state.discard_for_expired_link(
                account_id=row.admin_account_id,
                purpose=row.purpose,
                current_time=link.issued_at,
            )
        replaced_rows = self._connection.execute(
            update(SecurityLinkModel)
            .where(
                SecurityLinkModel.admin_account_id == link.account_id,
                SecurityLinkModel.purpose == link.purpose,
                SecurityLinkModel.status == "active",
            )
            .values(
                status="invalidated",
                invalidated_at=link.issued_at,
                updated_at=link.issued_at,
            )
            .returning(
                SecurityLinkModel.admin_account_id,
                SecurityLinkModel.purpose,
            )
        ).all()
        for row in replaced_rows:
            # Email change releases its old reservation before T073 claims the new one.
            if row.purpose != "email_change":
                self._pending_state.discard_for_replaced_link(
                    account_id=row.admin_account_id,
                    purpose=row.purpose,
                    current_time=link.issued_at,
                )
        row = self._connection.execute(
            insert(SecurityLinkModel)
            .values(
                admin_account_id=link.account_id,
                purpose=link.purpose,
                token_digest=link.token_digest,
                key_version=link.key_version,
                issued_at=link.issued_at,
                expires_at=link.expires_at,
                status=link.status,
                delivery_status=link.delivery_status,
            )
            .returning(
                SecurityLinkModel.security_link_id,
                SecurityLinkModel.admin_account_id,
                SecurityLinkModel.purpose,
                SecurityLinkModel.expires_at,
            )
        ).one()
        return _stored_link(row)

    def inspect_active(
        self, *, token_digest: bytes, purpose: SecurityLinkPurpose, now: datetime
    ) -> StoredSecurityLink | None:
        """Read a non-expired active link without locking or consuming it."""

        self._expire_matching_link(
            token_digest=token_digest,
            purpose=purpose,
            now=now,
        )
        row = self._connection.execute(
            select(
                SecurityLinkModel.security_link_id,
                SecurityLinkModel.admin_account_id,
                SecurityLinkModel.purpose,
                SecurityLinkModel.expires_at,
            ).where(
                SecurityLinkModel.token_digest == token_digest,
                SecurityLinkModel.purpose == purpose,
                SecurityLinkModel.status == "active",
                SecurityLinkModel.expires_at > now,
            )
        ).one_or_none()
        return None if row is None else _stored_link(row)

    def consume_active(
        self, *, token_digest: bytes, purpose: SecurityLinkPurpose, now: datetime
    ) -> StoredSecurityLink | None:
        """Allow exactly one transaction to consume a matching unexpired link."""

        row = self._connection.execute(
            update(SecurityLinkModel)
            .where(
                SecurityLinkModel.token_digest == token_digest,
                SecurityLinkModel.purpose == purpose,
                SecurityLinkModel.status == "active",
                SecurityLinkModel.expires_at > now,
            )
            .values(status="consumed", consumed_at=now, updated_at=now)
            .returning(
                SecurityLinkModel.security_link_id,
                SecurityLinkModel.admin_account_id,
                SecurityLinkModel.purpose,
                SecurityLinkModel.expires_at,
            )
        ).one_or_none()
        if row is not None:
            return _stored_link(row)

        self._expire_matching_link(token_digest=token_digest, purpose=purpose, now=now)
        return None

    def mark_delivery_accepted(self, *, link_id: int, current_time: datetime) -> None:
        """Persist provider acceptance only while this exact link remains active."""

        self._connection.execute(
            update(SecurityLinkModel)
            .where(
                SecurityLinkModel.security_link_id == link_id,
                SecurityLinkModel.status == "active",
                SecurityLinkModel.delivery_status == "pending",
            )
            .values(delivery_status="accepted", updated_at=current_time)
        )

    def invalidate_failed_delivery(
        self, *, link_id: int, current_time: datetime
    ) -> None:
        """Invalidate only a still-active failed link and record its safe failure."""

        self._connection.execute(
            update(SecurityLinkModel)
            .where(
                SecurityLinkModel.security_link_id == link_id,
                SecurityLinkModel.delivery_status == "pending",
            )
            .values(
                status="invalidated",
                delivery_status="failed",
                invalidated_at=current_time,
                updated_at=current_time,
            )
        )

    def _expire_matching_link(
        self,
        *,
        token_digest: bytes,
        purpose: SecurityLinkPurpose,
        now: datetime,
    ) -> None:
        rows = self._connection.execute(
            update(SecurityLinkModel)
            .where(
                SecurityLinkModel.token_digest == token_digest,
                SecurityLinkModel.purpose == purpose,
                SecurityLinkModel.status == "active",
                SecurityLinkModel.expires_at <= now,
            )
            .values(status="expired", updated_at=now)
            .returning(
                SecurityLinkModel.admin_account_id,
                SecurityLinkModel.purpose,
            )
        ).all()
        for row in rows:
            self._pending_state.discard_for_expired_link(
                account_id=row.admin_account_id,
                purpose=row.purpose,
                current_time=now,
            )


def _stored_link(row) -> StoredSecurityLink:
    return StoredSecurityLink(
        link_id=row.security_link_id,
        account_id=row.admin_account_id,
        purpose=row.purpose,
        expires_at=row.expires_at,
    )
