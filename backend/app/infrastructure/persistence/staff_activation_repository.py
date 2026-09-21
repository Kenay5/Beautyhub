"""PostgreSQL atomic transition for staff invitation activation."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Connection, insert, select, update
from backend.app.application.admin_access.staff_activation import LockedStaffActivation, StaffActivationStore
from backend.app.domain.authentication.recovery_code import RecoveryCode
from backend.app.domain.authentication.totp_factor import TotpFactor
from backend.app.infrastructure.persistence.models import AdminAccount, AdminEmailClaim, PendingSecuritySetup, RecoveryCode as RecoveryCodeModel, SecurityLink, TotpFactor as TotpFactorModel, TotpPeriodUse

class PostgresStaffActivationStore(StaffActivationStore):
    def __init__(self, connection: Connection): self._connection=connection
    def lock_candidate(self, *, link_id:int, account_id:int, current_time:datetime):
        account=self._connection.execute(select(AdminAccount.role,AdminAccount.status).where(AdminAccount.admin_account_id==account_id).with_for_update()).one_or_none()
        if account is None or tuple(account)!=("staff","pending"): return None
        claim=self._connection.execute(select(AdminEmailClaim.admin_email_claim_id).where(AdminEmailClaim.admin_account_id==account_id,AdminEmailClaim.claim_kind=="current").with_for_update()).scalar_one_or_none()
        if claim is None: return None
        link=self._connection.execute(select(SecurityLink.security_link_id).where(SecurityLink.security_link_id==link_id,SecurityLink.admin_account_id==account_id,SecurityLink.purpose=="invitation",SecurityLink.status=="active",SecurityLink.expires_at>current_time).with_for_update()).scalar_one_or_none()
        if link is None: return None
        setup=self._connection.execute(select(PendingSecuritySetup.pending_security_setup_id,PendingSecuritySetup.totp_secret_ciphertext,PendingSecuritySetup.key_version).where(PendingSecuritySetup.admin_account_id==account_id,PendingSecuritySetup.flow=="staff_activation",PendingSecuritySetup.status=="pending",PendingSecuritySetup.expires_at>current_time).with_for_update()).one_or_none()
        return None if setup is None else LockedStaffActivation(link_id=link_id,account_id=account_id,setup_id=setup.pending_security_setup_id,pending_totp_ciphertext=setup.totp_secret_ciphertext,pending_key_version=setup.key_version)
    def discard_pending(self, *, candidate, current_time):
        self._connection.execute(update(PendingSecuritySetup).where(PendingSecuritySetup.pending_security_setup_id==candidate.setup_id,PendingSecuritySetup.status=="pending").values(status="invalidated",totp_secret_ciphertext=None,key_version=None,updated_at=current_time))
    def activate(self, *, candidate, password_hash, factor:TotpFactor, period_counter, recovery_codes:tuple[RecoveryCode,...], current_time):
        factor_id=self._connection.execute(insert(TotpFactorModel).values(admin_account_id=factor.account_id,totp_secret_ciphertext=factor.secret_ciphertext,key_version=factor.key_version,algorithm=factor.algorithm,digits=factor.digits,period_seconds=factor.period_seconds,status=factor.status,confirmed_at=factor.confirmed_at,invalidated_at=None).returning(TotpFactorModel.totp_factor_id)).scalar_one()
        self._connection.execute(insert(TotpPeriodUse).values(admin_account_id=candidate.account_id,totp_factor_id=factor_id,period_counter=period_counter,consumed_at=current_time))
        self._connection.execute(insert(RecoveryCodeModel),[{"admin_account_id":x.account_id,"lookup_digest":x.lookup_digest,"key_version":x.key_version,"position":x.position,"status":x.status,"used_at":None,"invalidated_at":None} for x in recovery_codes])
        for statement in (
            update(AdminAccount).where(AdminAccount.admin_account_id==candidate.account_id,AdminAccount.status=="pending").values(status="active",password_hash=password_hash,updated_at=current_time),
            update(PendingSecuritySetup).where(PendingSecuritySetup.pending_security_setup_id==candidate.setup_id,PendingSecuritySetup.status=="pending").values(status="confirmed",totp_secret_ciphertext=None,key_version=None,updated_at=current_time),
            update(SecurityLink).where(SecurityLink.security_link_id==candidate.link_id,SecurityLink.status=="active").values(status="consumed",consumed_at=current_time,updated_at=current_time),
        ):
            if self._connection.execute(statement).rowcount != 1: raise RuntimeError("staff activation transition was not atomic.")
