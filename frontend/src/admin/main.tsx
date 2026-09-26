import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../shared/styles/base.css";
import { AdminApp } from "./AdminApp";
import { takeSecurityLinkTokenFromFragment } from "./securityLinkNavigation";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Administrative React root was not found.");
}

const securityLinkToken = ["/admin/security-link", "/admin/staff-activation", "/admin/password-recovery", "/admin/totp-replacement", "/admin/email-change"].includes(window.location.pathname)
  ? takeSecurityLinkTokenFromFragment(window.location, window.history)
  : null;

createRoot(rootElement).render(
  <StrictMode>
    <AdminApp securityLinkToken={securityLinkToken} />
  </StrictMode>,
);
