import { SecurityLinkFlow } from "./SecurityLinkFlow";
import { StaffInvitationPanel } from "./StaffInvitationPanel";

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

  return <StaffInvitationPanel />;
}
