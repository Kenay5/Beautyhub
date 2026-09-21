"""SQLAlchemy metadata for persistent BeautyHub entities."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base metadata for PostgreSQL persistence models."""


class Service(Base):
    """A bookable BeautyHub service and its fixed-branch availability."""

    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("char_length(name) >= 1", name="ck_services_name_nonempty"),
        CheckConstraint("name = btrim(name)", name="ck_services_name_trimmed"),
        CheckConstraint(
            "duration_minutes BETWEEN 5 AND 600 AND duration_minutes % 5 = 0",
            name="ck_services_duration_range_and_interval",
        ),
        CheckConstraint(
            "price > 0 AND price <= 20000.00 AND price = round(price, 2)",
            name="ck_services_price_range",
        ),
        CheckConstraint(
            "available_chiconcuac OR available_texcoco",
            name="ck_services_available_at_a_branch",
        ),
        UniqueConstraint("canonical_name", name="uq_services_canonical_name"),
    )

    service_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_name: Mapped[str] = mapped_column(
        String(100),
        Computed("lower(btrim(name))", persisted=True),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(String(250), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    available_chiconcuac: Mapped[bool] = mapped_column(Boolean, nullable=False)
    available_texcoco: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MonthlyAppointmentStatistic(Base):
    """A disassociated monthly aggregate retained after appointment removal."""

    __tablename__ = "monthly_appointment_statistics"
    __table_args__ = (
        CheckConstraint(
            "month_start = date_trunc('month', month_start)::date",
            name="ck_monthly_appointment_statistics_month_start",
        ),
        CheckConstraint(
            "branch IN ('chiconcuac', 'texcoco')",
            name="ck_monthly_appointment_statistics_branch",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed', 'no_show', "
            "'unrecorded_result')",
            name="ck_monthly_appointment_statistics_status",
        ),
        CheckConstraint(
            "appointment_count >= 0",
            name="ck_monthly_appointment_statistics_nonnegative_count",
        ),
        UniqueConstraint(
            "month_start",
            "service_id",
            "branch",
            "status",
            name="uq_monthly_appointment_statistics_aggregate",
        ),
    )

    monthly_appointment_statistic_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.service_id", ondelete="RESTRICT"), nullable=False
    )
    branch: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    appointment_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublicRequestEvent(Base):
    """A minimal, non-reversible event used for public abuse protection."""

    __tablename__ = "public_request_events"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(category)) > 0",
            name="ck_public_request_events_category_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(result)) > 0",
            name="ck_public_request_events_result_nonempty",
        ),
        CheckConstraint(
            "octet_length(subject_fingerprint) > 0",
            name="ck_public_request_events_fingerprint_nonempty",
        ),
        CheckConstraint(
            "expires_at > occurred_at",
            name="ck_public_request_events_expiry_range",
        ),
        Index(
            "ix_public_request_events_fingerprint_category_occurred_at",
            "subject_fingerprint",
            "category",
            "occurred_at",
        ),
        Index("ix_public_request_events_expires_at", "expires_at"),
    )

    public_request_event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PrivacyNoticeVersion(Base):
    """An immutable published version of the privacy notice."""

    __tablename__ = "privacy_notice_versions"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(version)) > 0",
            name="ck_privacy_notice_versions_version_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_privacy_notice_versions_content_nonempty",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_privacy_notice_versions_validity_range",
        ),
        UniqueConstraint("version", name="uq_privacy_notice_versions_version"),
    )

    privacy_notice_version_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Appointment(Base):
    """A scheduled appointment with immutable service and consent evidence."""

    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "char_length(first_name) BETWEEN 1 AND 100 "
            "AND first_name = btrim(first_name)",
            name="ck_appointments_first_name",
        ),
        CheckConstraint(
            "char_length(last_name) BETWEEN 1 AND 100 "
            "AND last_name = btrim(last_name)",
            name="ck_appointments_last_name",
        ),
        CheckConstraint(
            "phone ~ '^[0-9]{10}$'", name="ck_appointments_phone_format"
        ),
        CheckConstraint(
            "char_length(email) BETWEEN 1 AND 254 AND email = btrim(email)",
            name="ck_appointments_email_length_and_trimmed",
        ),
        CheckConstraint(
            "branch IN ('chiconcuac', 'texcoco')",
            name="ck_appointments_branch",
        ),
        CheckConstraint(
            "service_snapshot_name = btrim(service_snapshot_name) "
            "AND char_length(service_snapshot_name) BETWEEN 1 AND 100",
            name="ck_appointments_snapshot_name",
        ),
        CheckConstraint(
            "service_snapshot_duration_minutes BETWEEN 5 AND 600 "
            "AND service_snapshot_duration_minutes % 5 = 0",
            name="ck_appointments_snapshot_duration",
        ),
        CheckConstraint(
            "service_snapshot_price > 0 AND service_snapshot_price <= 20000.00 "
            "AND service_snapshot_price = round(service_snapshot_price, 2)",
            name="ck_appointments_snapshot_price",
        ),
        CheckConstraint(
            "scheduled_end > scheduled_start", name="ck_appointments_schedule_range"
        ),
        CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed', 'no_show', "
            "'unrecorded_result')",
            name="ck_appointments_status",
        ),
        CheckConstraint(
            "origin IN ('public', 'administrative')",
            name="ck_appointments_origin",
        ),
        CheckConstraint(
            "(origin = 'public' AND created_by_account_id IS NULL) OR "
            "(origin = 'administrative' AND created_by_account_id IS NOT NULL)",
            name="ck_appointments_origin_account",
        ),
        CheckConstraint(
            "contact_processing_authorized AND adult_responsibility_declared",
            name="ck_appointments_required_consent",
        ),
        CheckConstraint(
            "cancellation_reason IS NULL OR "
            "(char_length(cancellation_reason) <= 250 "
            "AND cancellation_reason = btrim(cancellation_reason))",
            name="ck_appointments_cancellation_reason",
        ),
        UniqueConstraint(
            "private_code_digest", name="uq_appointments_private_code_digest"
        ),
    )

    appointment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    private_code_ciphertext: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )
    private_code_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.service_id", ondelete="RESTRICT"), nullable=False
    )
    service_snapshot_name: Mapped[str] = mapped_column(String(100), nullable=False)
    service_snapshot_duration_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False
    )
    service_snapshot_price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    branch: Mapped[str] = mapped_column(String(20), nullable=False)
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(String(250), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_account_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    privacy_notice_version_id: Mapped[int] = mapped_column(
        ForeignKey("privacy_notice_versions.privacy_notice_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    privacy_notice_accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    contact_processing_authorized: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    adult_responsibility_declared: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BookingConfirmationReference(Base):
    """A one-time secret reference for an idempotent appointment confirmation."""

    __tablename__ = "booking_confirmation_references"
    __table_args__ = (
        CheckConstraint(
            "octet_length(reference_digest) > 0",
            name="ck_booking_confirmation_references_digest_nonempty",
        ),
        CheckConstraint(
            "expires_at = generated_at + interval '24 hours'",
            name="ck_booking_confirmation_references_exact_expiry",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR "
            "(consumed_at >= generated_at AND consumed_at < expires_at)",
            name="ck_booking_confirmation_references_consumption_range",
        ),
        UniqueConstraint(
            "reference_digest",
            name="uq_booking_confirmation_references_digest",
        ),
        UniqueConstraint(
            "appointment_id",
            name="uq_booking_confirmation_references_appointment",
        ),
    )

    booking_confirmation_reference_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    reference_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    appointment_id: Mapped[int | None] = mapped_column(
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NotificationDelivery(Base):
    """A per-channel transactional notification attempt for an appointment."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(event)) > 0",
            name="ck_notification_deliveries_event_nonempty",
        ),
        CheckConstraint(
            "channel IN ('email', 'whatsapp')",
            name="ck_notification_deliveries_channel",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'delivered', 'failed')",
            name="ck_notification_deliveries_status",
        ),
        CheckConstraint(
            "sanitized_error IS NULL OR char_length(btrim(sanitized_error)) > 0",
            name="ck_notification_deliveries_sanitized_error_nonempty",
        ),
        ForeignKeyConstraint(
            ["appointment_reminder_id", "appointment_id"],
            [
                "appointment_reminders.appointment_reminder_id",
                "appointment_reminders.appointment_id",
            ],
            name="fk_notification_deliveries_reminder_appointment",
            ondelete="CASCADE",
        ),
        Index(
            "uq_notification_deliveries_reminder_channel",
            "appointment_reminder_id",
            "channel",
            unique=True,
            postgresql_where=text("appointment_reminder_id IS NOT NULL"),
        ),
    )

    notification_delivery_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    appointment_reminder_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    previous_delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "notification_deliveries.notification_delivery_id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    sanitized_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AppointmentReminder(Base):
    """A durable reminder tied to one appointment schedule version."""

    __tablename__ = "appointment_reminders"
    __table_args__ = (
        CheckConstraint(
            "send_at = appointment_scheduled_start - interval '24 hours'",
            name="ck_appointment_reminders_exact_send_time",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'claimed', 'completed', 'invalidated', 'omitted')",
            name="ck_appointment_reminders_status",
        ),
        CheckConstraint(
            "(status = 'claimed' AND claimed_at IS NOT NULL "
            "AND claim_expires_at > claimed_at) OR "
            "(status <> 'claimed' AND claimed_at IS NULL "
            "AND claim_expires_at IS NULL)",
            name="ck_appointment_reminders_claim_state",
        ),
        UniqueConstraint(
            "appointment_id",
            "appointment_scheduled_start",
            name="uq_appointment_reminders_appointment_schedule",
        ),
        UniqueConstraint(
            "appointment_reminder_id",
            "appointment_id",
            name="uq_appointment_reminders_id_appointment",
        ),
    )

    appointment_reminder_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"), nullable=False
    )
    appointment_scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AvailabilityBlock(Base):
    """A one-time availability block for all branches or one branch."""

    __tablename__ = "availability_blocks"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('global', 'branch')",
            name="ck_availability_blocks_scope",
        ),
        CheckConstraint(
            "(scope = 'global' AND branch IS NULL) OR "
            "(scope = 'branch' AND branch IS NOT NULL "
            "AND branch IN ('chiconcuac', 'texcoco'))",
            name="ck_availability_blocks_scope_branch",
        ),
        CheckConstraint(
            "ends_at > starts_at", name="ck_availability_blocks_time_range"
        ),
    )

    availability_block_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(20), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScheduleGuard(Base):
    """The singleton row that serializes schedule-changing transactions."""

    __tablename__ = "schedule_guard"
    __table_args__ = (
        CheckConstraint("guard_id = 1", name="ck_schedule_guard_singleton"),
    )

    guard_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


class AdminAccount(Base):
    """Administrative account identity without credential material."""

    __tablename__ = "admin_accounts"
    __table_args__ = (
        CheckConstraint(
            "(role = 'owner' AND status IN ('inactive', 'active')) OR "
            "(role = 'staff' AND status IN ('pending', 'active', 'deactivated'))",
            name="ck_admin_accounts_role_status",
        ),
        Index(
            "uq_admin_accounts_single_owner",
            "role",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
        Index(
            "uq_admin_accounts_single_pending_or_active_staff",
            "role",
            unique=True,
            postgresql_where=text(
                "role = 'staff' AND status IN ('pending', 'active')"
            ),
        ),
    )

    admin_account_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OwnerBootstrapState(Base):
    """The one irreversible administrative owner bootstrap process."""

    __tablename__ = "owner_bootstrap_state"
    __table_args__ = (
        CheckConstraint(
            "bootstrap_state_id = 1", name="ck_owner_bootstrap_state_singleton"
        ),
        CheckConstraint(
            "status IN ('open', 'closed')",
            name="ck_owner_bootstrap_state_status",
        ),
        CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status = 'closed' AND owner_account_id IS NOT NULL "
            "AND closed_at IS NOT NULL)",
            name="ck_owner_bootstrap_state_closure",
        ),
    )

    bootstrap_state_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="RESTRICT"),
        nullable=True,
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AdminEmailClaim(Base):
    """A current or reserved administrative email without plaintext storage."""

    __tablename__ = "admin_email_claims"
    __table_args__ = (
        CheckConstraint(
            "claim_kind IN ('current', 'reserved')",
            name="ck_admin_email_claims_kind",
        ),
        CheckConstraint(
            "octet_length(lookup_digest) = 32",
            name="ck_admin_email_claims_lookup_digest_length",
        ),
        CheckConstraint(
            "octet_length(email_ciphertext) > 0",
            name="ck_admin_email_claims_ciphertext_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(key_version)) > 0",
            name="ck_admin_email_claims_key_version_nonempty",
        ),
        UniqueConstraint(
            "lookup_digest", name="uq_admin_email_claims_lookup_digest"
        ),
        Index(
            "uq_admin_email_claims_current_per_account",
            "admin_account_id",
            unique=True,
            postgresql_where=text("claim_kind = 'current'"),
        ),
        Index(
            "uq_admin_email_claims_reserved_per_account",
            "admin_account_id",
            unique=True,
            postgresql_where=text("claim_kind = 'reserved'"),
        ),
    )

    admin_email_claim_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    lookup_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    email_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityLink(Base):
    """A one-use administrative link stored only by token digest."""

    __tablename__ = "security_links"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('initial_activation', 'invitation', 'password_recovery', "
            "'forced_password_reset', 'totp_replacement', 'email_change')",
            name="ck_security_links_purpose",
        ),
        CheckConstraint(
            "octet_length(token_digest) = 32",
            name="ck_security_links_token_digest_length",
        ),
        CheckConstraint(
            "expires_at > issued_at",
            name="ck_security_links_expiry_range",
        ),
        CheckConstraint(
            "status IN ('active', 'consumed', 'invalidated', 'expired')",
            name="ck_security_links_status",
        ),
        CheckConstraint(
            "delivery_status IN ('pending', 'accepted', 'failed', 'uncertain')",
            name="ck_security_links_delivery_status",
        ),
        CheckConstraint(
            "(status = 'active' AND consumed_at IS NULL AND invalidated_at IS NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND consumed_at IS NULL AND invalidated_at IS NOT NULL) OR "
            "(status = 'expired' AND consumed_at IS NULL AND invalidated_at IS NULL)",
            name="ck_security_links_state_timestamps",
        ),
        UniqueConstraint("token_digest", name="uq_security_links_token_digest"),
        Index(
            "uq_security_links_active_account_purpose",
            "admin_account_id",
            "purpose",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    security_link_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    token_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PendingSecuritySetup(Base):
    """Encrypted, incomplete TOTP configuration awaiting confirmation."""

    __tablename__ = "pending_security_setups"
    __table_args__ = (
        CheckConstraint(
            "flow IN ('owner_activation', 'staff_activation', 'totp_replacement')",
            name="ck_pending_security_setups_flow",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'invalidated', 'expired')",
            name="ck_pending_security_setups_status",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_pending_security_setups_expiry_range",
        ),
        CheckConstraint(
            "(status = 'pending' AND totp_secret_ciphertext IS NOT NULL "
            "AND key_version IS NOT NULL AND char_length(btrim(key_version)) > 0) OR "
            "(status <> 'pending' AND totp_secret_ciphertext IS NULL AND key_version IS NULL)",
            name="ck_pending_security_setups_secret_lifecycle",
        ),
        Index(
            "uq_pending_security_setups_account_flow",
            "admin_account_id",
            "flow",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    pending_security_setup_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        nullable=False,
    )
    flow: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    totp_secret_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    key_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TotpFactor(Base):
    """A confirmed administrative TOTP factor with recoverable encrypted material."""

    __tablename__ = "totp_factors"
    __table_args__ = (
        CheckConstraint(
            "algorithm IN ('SHA1', 'SHA256', 'SHA512')",
            name="ck_totp_factors_algorithm",
        ),
        CheckConstraint("digits = 6", name="ck_totp_factors_six_digits"),
        CheckConstraint(
            "period_seconds = 30", name="ck_totp_factors_thirty_second_period"
        ),
        CheckConstraint(
            "status IN ('active', 'invalidated')",
            name="ck_totp_factors_status",
        ),
        CheckConstraint(
            "(status = 'active' AND totp_secret_ciphertext IS NOT NULL "
            "AND octet_length(totp_secret_ciphertext) > 0 "
            "AND key_version IS NOT NULL AND char_length(btrim(key_version)) > 0 "
            "AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND totp_secret_ciphertext IS NULL "
            "AND key_version IS NULL AND invalidated_at IS NOT NULL)",
            name="ck_totp_factors_secret_lifecycle",
        ),
        UniqueConstraint(
            "totp_factor_id",
            "admin_account_id",
            name="uq_totp_factors_id_account",
        ),
        Index(
            "uq_totp_factors_active_per_account",
            "admin_account_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    totp_factor_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        nullable=False,
    )
    totp_secret_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    key_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    algorithm: Mapped[str] = mapped_column(String(10), nullable=False)
    digits: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TotpPeriodUse(Base):
    """A committed single use of one TOTP factor counter."""

    __tablename__ = "totp_period_uses"
    __table_args__ = (
        CheckConstraint(
            "period_counter >= 0", name="ck_totp_period_uses_counter_nonnegative"
        ),
        UniqueConstraint(
            "admin_account_id",
            "totp_factor_id",
            "period_counter",
            name="uq_totp_period_uses_account_factor_counter",
        ),
        ForeignKeyConstraint(
            ["totp_factor_id", "admin_account_id"],
            ["totp_factors.totp_factor_id", "totp_factors.admin_account_id"],
            ondelete="CASCADE",
        ),
    )

    totp_period_use_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    totp_factor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_counter: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class RecoveryCode(Base):
    """A recovery code represented only by a purpose-separated HMAC digest."""

    __tablename__ = "recovery_codes"
    __table_args__ = (
        CheckConstraint(
            "octet_length(lookup_digest) = 32",
            name="ck_recovery_codes_lookup_digest_length",
        ),
        CheckConstraint(
            "char_length(btrim(key_version)) > 0",
            name="ck_recovery_codes_key_version_nonempty",
        ),
        CheckConstraint(
            "position BETWEEN 1 AND 10", name="ck_recovery_codes_position_range"
        ),
        CheckConstraint(
            "status IN ('active', 'used', 'invalidated')",
            name="ck_recovery_codes_status",
        ),
        CheckConstraint(
            "(status = 'active' AND used_at IS NULL AND invalidated_at IS NULL) OR "
            "(status = 'used' AND used_at IS NOT NULL AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND invalidated_at IS NOT NULL)",
            name="ck_recovery_codes_state_timestamps",
        ),
        UniqueConstraint("lookup_digest", name="uq_recovery_codes_lookup_digest"),
        Index(
            "uq_recovery_codes_active_account_position",
            "admin_account_id",
            "position",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    recovery_code_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        nullable=False,
    )
    lookup_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminSession(Base):
    """An opaque administrative session with only lookup digests persisted."""

    __tablename__ = "admin_sessions"
    __table_args__ = (
        CheckConstraint(
            "octet_length(session_digest) = 32",
            name="ck_admin_sessions_session_digest_length",
        ),
        CheckConstraint(
            "octet_length(csrf_digest) = 32",
            name="ck_admin_sessions_csrf_digest_length",
        ),
        CheckConstraint(
            "char_length(btrim(key_version)) > 0",
            name="ck_admin_sessions_key_version_nonempty",
        ),
        CheckConstraint(
            "absolute_expires_at = created_at + INTERVAL '8 hours'",
            name="ck_admin_sessions_absolute_expiry",
        ),
        CheckConstraint(
            "last_human_activity_at >= created_at "
            "AND last_human_activity_at <= absolute_expires_at",
            name="ck_admin_sessions_activity_range",
        ),
        CheckConstraint(
            "status IN ('active', 'invalidated')",
            name="ck_admin_sessions_status",
        ),
        CheckConstraint(
            "(status = 'active' AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND invalidated_at IS NOT NULL)",
            name="ck_admin_sessions_invalidation_state",
        ),
        UniqueConstraint("session_digest", name="uq_admin_sessions_session_digest"),
        Index(
            "uq_admin_sessions_active_per_account",
            "admin_account_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    admin_session_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        nullable=False,
    )
    session_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    csrf_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_human_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AdminCredentialFailureEvent(Base):
    """One rejected administrative credential request without its credentials."""

    __tablename__ = "admin_credential_failure_events"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('login', 'password_change', 'email_change', "
            "'totp_replacement', 'recovery_code_regeneration')",
            name="ck_admin_credential_failure_events_operation",
        ),
        UniqueConstraint(
            "admin_credential_failure_event_id",
            "admin_account_id",
            name="uq_admin_credential_failure_events_id_account",
        ),
        Index(
            "ix_admin_credential_failure_events_account_occurred_at",
            "admin_account_id",
            "occurred_at",
        ),
    )

    admin_credential_failure_event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AdminAccountSecurityState(Base):
    """The one row locked to update administrative account-security state."""

    __tablename__ = "admin_account_security_states"
    __table_args__ = (
        CheckConstraint(
            "(lock_until IS NULL AND fifth_failure_event_id IS NULL) OR "
            "(lock_until IS NOT NULL AND fifth_failure_event_id IS NOT NULL)",
            name="ck_admin_account_security_states_lock_reference",
        ),
        ForeignKeyConstraint(
            ["fifth_failure_event_id", "admin_account_id"],
            [
                "admin_credential_failure_events.admin_credential_failure_event_id",
                "admin_credential_failure_events.admin_account_id",
            ],
        ),
    )

    admin_account_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
        primary_key=True,
    )
    lock_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fifth_failure_event_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    post_recovery_second_factor_restricted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RateLimitEvent(Base):
    """An idempotent moving-window reservation with opaque identifiers only."""

    __tablename__ = "rate_limit_events"
    __table_args__ = (
        CheckConstraint(
            "category IN ('authentication_recovery_lost_factor', "
            "'authenticated_administrative_operation', 'security_message_action', "
            "'appointment_notification_operation')",
            name="ck_rate_limit_events_category",
        ),
        CheckConstraint(
            "octet_length(subject_fingerprint) = 32",
            name="ck_rate_limit_events_subject_fingerprint_length",
        ),
        CheckConstraint(
            "octet_length(request_fingerprint) = 32",
            name="ck_rate_limit_events_request_fingerprint_length",
        ),
        UniqueConstraint(
            "category",
            "subject_fingerprint",
            "request_fingerprint",
            name="uq_rate_limit_events_idempotent_request",
        ),
        Index(
            "ix_rate_limit_events_subject_category_occurred_at",
            "subject_fingerprint",
            "category",
            "occurred_at",
        ),
    )

    rate_limit_event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    request_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RateLimitGuard(Base):
    """The locked guard that serializes one opaque subject and limit category."""

    __tablename__ = "rate_limit_guards"
    __table_args__ = (
        CheckConstraint(
            "category IN ('authentication_recovery_lost_factor', "
            "'authenticated_administrative_operation', 'security_message_action', "
            "'appointment_notification_operation')",
            name="ck_rate_limit_guards_category",
        ),
        CheckConstraint(
            "octet_length(subject_fingerprint) = 32",
            name="ck_rate_limit_guards_subject_fingerprint_length",
        ),
        UniqueConstraint(
            "category",
            "subject_fingerprint",
            name="uq_rate_limit_guards_subject_category",
        ),
    )

    rate_limit_guard_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class AdminAuditEvent(Base):
    """Minimum administrative-history evidence without copied private data."""

    __tablename__ = "admin_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('login', 'account_locked', 'logout', 'account_activation', "
            "'staff_invitation', 'staff_deactivation', 'password_change', "
            "'password_recovery', 'email_change', 'totp_replacement', "
            "'recovery_code_regeneration', 'appointment_created', "
            "'appointment_modified', 'appointment_cancelled', "
            "'appointment_result_recorded', 'appointment_private_code_resent', "
            "'availability_block_created', 'availability_block_modified', "
            "'availability_block_deleted', 'service_created', 'service_modified', "
            "'service_activated', 'service_deactivated', 'authorization_denied')",
            name="ck_admin_audit_events_action",
        ),
        CheckConstraint(
            "result IN ('succeeded', 'failed', 'denied')",
            name="ck_admin_audit_events_result",
        ),
        CheckConstraint(
            "target_reference IS NULL OR "
            "target_reference ~ "
            "'^(appointment|availability_block|service|admin_account):[1-9][0-9]*$'",
            name="ck_admin_audit_events_internal_reference",
        ),
        Index(
            "ix_admin_audit_events_actor_occurred_at",
            "actor_account_id",
            "occurred_at",
        ),
        Index(
            "ix_admin_audit_events_action_occurred_at",
            "action",
            "occurred_at",
        ),
    )

    admin_audit_event_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    actor_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_accounts.admin_account_id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    target_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)


class SecurityNotificationDelivery(Base):
    """A private, idempotent administrative security-delivery intention."""

    __tablename__ = "security_notification_deliveries"
    __table_args__ = (
        CheckConstraint(
            "event ~ '^[a-z][a-z0-9_]{0,99}$'",
            name="ck_security_notification_deliveries_event",
        ),
        CheckConstraint(
            "template ~ '^[a-z][a-z0-9_]{0,99}$'",
            name="ck_security_notification_deliveries_template",
        ),
        CheckConstraint(
            "(recipient_ciphertext IS NOT NULL "
            "AND octet_length(recipient_ciphertext) > 0 "
            "AND recipient_key_version IS NOT NULL "
            "AND char_length(btrim(recipient_key_version)) > 0) "
            "OR (recipient_ciphertext IS NULL AND recipient_key_version IS NULL)",
            name="ck_security_notification_deliveries_recipient_lifecycle",
        ),
        CheckConstraint(
            "octet_length(idempotency_key_digest) = 32",
            name="ck_security_notification_deliveries_idempotency_digest_length",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'failed', 'uncertain')",
            name="ck_security_notification_deliveries_status",
        ),
        CheckConstraint(
            "(status = 'failed' AND sanitized_error = 'security delivery failed.') "
            "OR (status <> 'failed' AND sanitized_error IS NULL)",
            name="ck_security_notification_deliveries_sanitized_error",
        ),
        UniqueConstraint(
            "idempotency_key_digest",
            name="uq_security_notification_deliveries_idempotency_digest",
        ),
    )

    security_notification_delivery_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    recipient_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    recipient_key_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    sanitized_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
