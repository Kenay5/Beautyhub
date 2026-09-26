export type AdministrativeRole = "owner" | "staff";

export type AdministrativeSession = {
  accountId: number;
  role: AdministrativeRole;
  csrfToken: string;
};

export type AdministrativeLoginInput = {
  email: string;
  password: string;
  totpCode?: string;
  recoveryCode?: string;
};

type AdministrativeLoginSession = Pick<
  AdministrativeSession,
  "role" | "csrfToken"
>;

export class AdministrativeSessionUnavailableError extends Error {}

export class AdministrativePasswordChangeError extends Error {
  constructor(readonly kind: "credentials" | "password" | "forbidden" | "unavailable") {
    super("administrative password change failed");
  }
}

export class OwnEmailChangeError extends Error {
  constructor(readonly kind: "credentials" | "email" | "forbidden" | "unavailable" | "delivery") {
    super("administrative email change request failed");
  }
}

export class RecoveryCodeRegenerationError extends Error {
  constructor(readonly kind: "credentials" | "forbidden" | "unavailable") {
    super("recovery-code regeneration failed");
  }
}

export type PreparedAdministrativeTotpReplacement = {
  provisioningUri: string;
  manualKey: string;
};

export class TotpReplacementPreparationError extends Error {
  constructor(readonly kind: "credentials" | "forbidden" | "unavailable") {
    super("TOTP replacement preparation failed");
  }
}

export class TotpReplacementConfirmationError extends Error {
  constructor(readonly kind: "credentials" | "forbidden" | "unavailable") {
    super("TOTP replacement confirmation failed");
  }
}

export async function confirmAdministrativeTotpReplacement(input: {
  totpCode: string;
  csrfToken: string;
}): Promise<string[]> {
  const response = await fetch("/api/admin/totp-replacement/confirm", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": input.csrfToken,
    },
    body: JSON.stringify({ totpCode: input.totpCode }),
  });
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (response.status === 400) throw new TotpReplacementConfirmationError("credentials");
  if (response.status === 403) throw new TotpReplacementConfirmationError("forbidden");
  if (!response.ok) throw new TotpReplacementConfirmationError("unavailable");
  const payload: unknown = await response.json();
  if (!isRecoveryCodeResponse(payload)) {
    throw new TotpReplacementConfirmationError("unavailable");
  }
  return payload.recoveryCodes;
}

export async function prepareAdministrativeTotpReplacement(input: {
  currentPassword: string;
  totpCode?: string;
  recoveryCode?: string;
  csrfToken: string;
}): Promise<PreparedAdministrativeTotpReplacement> {
  const response = await fetch("/api/admin/totp-replacement/prepare", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": input.csrfToken,
    },
    body: JSON.stringify({
      currentPassword: input.currentPassword,
      ...(input.totpCode !== undefined ? { totpCode: input.totpCode } : {}),
      ...(input.recoveryCode !== undefined ? { recoveryCode: input.recoveryCode } : {}),
    }),
  });
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (response.status === 400) throw new TotpReplacementPreparationError("credentials");
  if (response.status === 403) throw new TotpReplacementPreparationError("forbidden");
  if (!response.ok) throw new TotpReplacementPreparationError("unavailable");
  const payload: unknown = await response.json();
  if (!isTotpReplacementSetup(payload)) {
    throw new TotpReplacementPreparationError("unavailable");
  }
  return payload;
}

export async function regenerateAdministrativeRecoveryCodes(input: {
  currentPassword: string;
  totpCode: string;
  csrfToken: string;
}): Promise<string[]> {
  const response = await fetch("/api/admin/recovery-codes/regenerate", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": input.csrfToken,
    },
    body: JSON.stringify({
      currentPassword: input.currentPassword,
      totpCode: input.totpCode,
    }),
  });
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (response.status === 400) throw new RecoveryCodeRegenerationError("credentials");
  if (response.status === 403) throw new RecoveryCodeRegenerationError("forbidden");
  if (!response.ok) throw new RecoveryCodeRegenerationError("unavailable");
  const payload: unknown = await response.json();
  if (!isRecoveryCodeResponse(payload)) {
    throw new RecoveryCodeRegenerationError("unavailable");
  }
  return payload.recoveryCodes;
}

export async function changeAdministrativePassword(input: {
  currentPassword: string;
  totpCode: string;
  newPassword: string;
  csrfToken: string;
}): Promise<void> {
  const response = await fetch("/api/admin/password", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": input.csrfToken,
    },
    body: JSON.stringify({
      currentPassword: input.currentPassword,
      totpCode: input.totpCode,
      newPassword: input.newPassword,
    }),
  });
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (response.status === 400) throw new AdministrativePasswordChangeError("credentials");
  if (response.status === 422) throw new AdministrativePasswordChangeError("password");
  if (response.status === 403) throw new AdministrativePasswordChangeError("forbidden");
  if (!response.ok) throw new AdministrativePasswordChangeError("unavailable");
}

export async function requestOwnAdministrativeEmailChange(input: {
  newEmail: string;
  currentPassword: string;
  totpCode: string;
  csrfToken: string;
}): Promise<void> {
  const response = await fetch("/api/admin/account/email-change", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": input.csrfToken,
    },
    body: JSON.stringify({
      newEmail: input.newEmail,
      currentPassword: input.currentPassword,
      totpCode: input.totpCode,
    }),
  });
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (response.status === 400) throw new OwnEmailChangeError("credentials");
  if (response.status === 422) throw new OwnEmailChangeError("email");
  if (response.status === 403) throw new OwnEmailChangeError("forbidden");
  if (response.status === 409) throw new OwnEmailChangeError("unavailable");
  if (!response.ok) throw new OwnEmailChangeError("unavailable");
  const payload: unknown = await response.json();
  if (!isOwnEmailChangeResponse(payload)) {
    throw new OwnEmailChangeError("unavailable");
  }
  if (payload.deliveryStatus === "failed") {
    throw new OwnEmailChangeError("delivery");
  }
}

export async function loadAdministrativeSession(
  signal?: AbortSignal,
): Promise<AdministrativeSession> {
  const response = await fetch("/api/admin/sessions/current", {
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  return readSessionResponse(response);
}

export async function createAdministrativeSession(
  input: AdministrativeLoginInput,
): Promise<AdministrativeLoginSession> {
  const response = await fetch("/api/admin/sessions", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (!response.ok) throw new Error("administrative login is unavailable");
  const payload: unknown = await response.json();
  if (!isAdministrativeLoginSession(payload)) {
    throw new Error("administrative login response is invalid");
  }
  return payload;
}

export async function closeAdministrativeSession(
  csrfToken: string,
): Promise<void> {
  const response = await fetch("/api/admin/sessions/current", {
    method: "DELETE",
    cache: "no-store",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrfToken },
  });
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (!response.ok) throw new Error("administrative logout is unavailable");
}

async function readSessionResponse(
  response: Response,
): Promise<AdministrativeSession> {
  if (response.status === 401) throw new AdministrativeSessionUnavailableError();
  if (!response.ok) throw new Error("administrative session is unavailable");
  const payload: unknown = await response.json();
  if (!isAdministrativeSession(payload)) {
    throw new Error("administrative session response is invalid");
  }
  return payload;
}

function isAdministrativeSession(value: unknown): value is AdministrativeSession {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.accountId === "number" &&
    Number.isSafeInteger(candidate.accountId) &&
    candidate.accountId > 0 &&
    (candidate.role === "owner" || candidate.role === "staff") &&
    typeof candidate.csrfToken === "string" &&
    candidate.csrfToken.length > 0
  );
}

function isAdministrativeLoginSession(
  value: unknown,
): value is AdministrativeLoginSession {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    (candidate.role === "owner" || candidate.role === "staff") &&
    typeof candidate.csrfToken === "string" &&
    candidate.csrfToken.length > 0
  );
}

function isRecoveryCodeResponse(
  value: unknown,
): value is { recoveryCodes: string[] } {
  if (typeof value !== "object" || value === null || !("recoveryCodes" in value)) {
    return false;
  }
  const codes = value.recoveryCodes;
  return (
    Array.isArray(codes) &&
    codes.length === 10 &&
    new Set(codes).size === 10 &&
    codes.every(
      (code) =>
        typeof code === "string" &&
        /^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}$/.test(code),
    )
  );
}

function isTotpReplacementSetup(
  value: unknown,
): value is PreparedAdministrativeTotpReplacement {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.provisioningUri === "string" &&
    candidate.provisioningUri.startsWith("otpauth://totp/") &&
    typeof candidate.manualKey === "string" &&
    /^[A-Z2-7]{32}$/.test(candidate.manualKey)
  );
}

function isOwnEmailChangeResponse(
  value: unknown,
): value is { deliveryStatus: "accepted" | "failed"; detail: string } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    (candidate.deliveryStatus === "accepted" || candidate.deliveryStatus === "failed") &&
    typeof candidate.detail === "string"
  );
}
