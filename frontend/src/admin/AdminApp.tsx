import { AdminSessionGate } from "./AdminSessionGate";
import { SecurityLinkFlow } from "./SecurityLinkFlow";
import { PasswordRecoveryFlow } from "./PasswordRecoveryFlow";
import { LostFactorReplacementFlow } from "./LostFactorReplacementFlow";
import { OwnEmailChangeConfirmationFlow } from "./OwnEmailChangeConfirmationFlow";

type AdminAppProps = {
  securityLinkToken: string | null;
};

export function AdminApp({ securityLinkToken }: AdminAppProps) {
  if (window.location.pathname === "/admin/security-link") {
    return <SecurityLinkFlow token={securityLinkToken} />;
  }
  if (window.location.pathname === "/admin/staff-activation") {
    return <SecurityLinkFlow endpointPrefix="/api/admin/staff-security-links" token={securityLinkToken} />;
  }
  if (window.location.pathname === "/admin/password-recovery") {
    return <PasswordRecoveryFlow token={securityLinkToken} />;
  }
  if (window.location.pathname === "/admin/totp-replacement") {
    return <LostFactorReplacementFlow token={securityLinkToken} />;
  }
  if (window.location.pathname === "/admin/email-change") {
    return <OwnEmailChangeConfirmationFlow token={securityLinkToken} />;
  }

  return <AdminSessionGate />;
}
