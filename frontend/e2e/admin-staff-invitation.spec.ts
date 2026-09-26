import { createHmac } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";


const ownerEmail = "synthetic.owner@example.test";
const ownerPassword = "synthetic owner phrase for browser tests";
const ownerRecoveryCode = "ABCD-EFGH-JKLM-NPQR";
const ownerTotpSecret = "JBSWY3DPEHPK3PXP";
const staffEmail = "synthetic.staff@example.test";
const staffPassword = "synthetic staff phrase for browser tests";
const genericLinkMessage = "Este enlace no es válido o ya no está disponible.";

type Mail = { outcome: "accepted" | "failed"; content: string };
type AccountState = {
  status: string;
  claimKinds: string[];
  links: Array<{
    status: string;
    deliveryStatus: string;
    issuedAt: string;
    expiresAt: string;
  }>;
  factorStatus: string | null;
  activeRecoveryCodes: number;
  activeSessions: number;
};

test("T042 completes owner invitation, delivery recovery, cancellation, expiry, and staff activation", async ({
  page,
  browser,
  request,
}) => {
  await expect((await request.post("/__test__/staff-invitations/reset")).status()).toBe(204);
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  await page.getByLabel("Correo electrónico").fill(ownerEmail);
  await page.getByLabel("Contraseña").fill(ownerPassword);
  await page.getByRole("button", { name: "Usar un código de recuperación" }).click();
  await page.getByRole("textbox", { name: "Código de recuperación" }).fill(ownerRecoveryCode);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  await expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await request.put("/__test__/staff-invitations/mailbox/outcome", {
    data: { outcome: "failed" },
  });
  await page.getByRole("button", { name: "Cerrar sesión" }).focus();
  await page.keyboard.press("Tab");
  const staffEmailInput = page.getByLabel("Correo del personal");
  await expect(staffEmailInput).toBeFocused();
  await page.keyboard.type(staffEmail);
  await page.keyboard.press("Tab");
  const inviteButton = page.getByRole("button", { name: "Enviar invitación" });
  await expect(inviteButton).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("No se pudo enviar el correo. Inténtalo de nuevo.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reenviar invitación" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar invitación" })).toBeVisible();
  await expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const failedMail = await takeMail(request);
  expect(failedMail.outcome).toBe("failed");
  const failedToken = extractToken(failedMail.content);
  const firstAccount = await findAccount(request, staffEmail);
  let state = await loadState(request, firstAccount);
  expect(state.status).toBe("pending");
  expect(state.claimKinds).toEqual(["current"]);
  expect(state.links.map(({ status, deliveryStatus }) => [status, deliveryStatus])).toEqual([
    ["invalidated", "failed"],
  ]);

  const staffContext = await browser.newContext();
  const staffPage = await staffContext.newPage();
  try {
    expect(await openLink(staffPage, failedToken)).toBe(404);
    await expect(staffPage.getByText(genericLinkMessage)).toBeVisible();

    await page.getByRole("button", { name: "Reenviar invitación" }).click();
    await expect(page.getByText("La invitación está pendiente y el enlace fue enviado.")).toBeVisible();
    const resentMail = await takeMail(request);
    expect(resentMail.outcome).toBe("accepted");
    const resentToken = extractToken(resentMail.content);
    expect(resentToken === failedToken).toBe(false);
    state = await loadState(request, firstAccount);
    expect(state.status).toBe("pending");
    expect(state.links.map(({ status, deliveryStatus }) => [status, deliveryStatus])).toEqual([
      ["invalidated", "failed"],
      ["active", "accepted"],
    ]);
    expect(lifetimeSeconds(state.links[1])).toBe(24 * 60 * 60);

    await page.getByRole("button", { name: "Cancelar invitación" }).click();
    await expect(page.getByText("La invitación fue cancelada. Ya puedes crear una nueva.")).toBeVisible();
    state = await loadState(request, firstAccount);
    expect(state.status).toBe("deactivated");
    expect(state.claimKinds).toEqual([]);
    expect(state.links.map(({ status }) => status)).toEqual(["invalidated", "invalidated"]);
    expect(await openLink(staffPage, resentToken)).toBe(404);
    await expect(staffPage.getByText(genericLinkMessage)).toBeVisible();

    await request.put("/__test__/staff-invitations/mailbox/outcome", {
      data: { outcome: "accepted" },
    });
    await page.getByLabel("Correo del personal").fill(staffEmail);
    await page.getByRole("button", { name: "Enviar invitación" }).click();
    await expect(page.getByText("La invitación está pendiente y el enlace fue enviado.")).toBeVisible();
    const expiredMail = await takeMail(request);
    const secondAccount = await findAccount(request, staffEmail);
    const expiredToken = extractToken(expiredMail.content);
    const expireResponse = await request.post("/__test__/staff-invitations/expire-invitation", {
      data: { token: expiredToken },
    });
    expect(expireResponse.status()).toBe(204);
    const forcedExpiryState = await loadState(request, secondAccount);
    expect(Date.parse(forcedExpiryState.links[0].expiresAt) < Date.now()).toBe(true);

    expect(await openLink(staffPage, expiredToken)).toBe(404);
    await expect(staffPage.getByText(genericLinkMessage)).toBeVisible();
    state = await loadState(request, secondAccount);
    expect(state.status).toBe("pending");
    expect(state.claimKinds).toEqual(["current"]);
    expect(state.links.map(({ status }) => status)).toEqual(["active"]);
    expect(Date.parse(state.links[0].expiresAt) < Date.now()).toBe(true);

    await page.getByRole("button", { name: "Reenviar invitación" }).click();
    await expect(page.getByText("La invitación está pendiente y el enlace fue enviado.")).toBeVisible();
    const finalMail = await takeMail(request);
    const activationToken = extractToken(finalMail.content);
    expect(activationToken === expiredToken).toBe(false);
    state = await loadState(request, secondAccount);
    expect(state.links.map(({ status, deliveryStatus }) => [status, deliveryStatus])).toEqual([
      ["expired", "accepted"],
      ["active", "accepted"],
    ]);
    expect(lifetimeSeconds(state.links[1])).toBe(24 * 60 * 60);

    expect(await openLink(staffPage, activationToken)).toBe(200);
    await expect(staffPage.getByRole("heading", { name: "Activa tu cuenta" })).toBeVisible();
    await expect((await new AxeBuilder({ page: staffPage }).analyze()).violations).toEqual([]);
    await staffPage.getByRole("button", { name: "Continuar" }).click();
    await staffPage.getByLabel("Nueva contraseña").fill(staffPassword);
    await staffPage.getByLabel("Confirmar contraseña").fill(staffPassword);
    await staffPage.getByRole("button", { name: "Continuar" }).click();
    await expect(staffPage.getByRole("img", { name: "Código QR para configurar la aplicación de autenticación" })).toBeVisible();
    await staffPage.getByRole("button", { name: "Mostrar clave manual" }).click();
    const manualKey = (await staffPage.getByLabel("Clave manual de autenticación").innerText()).replaceAll(" ", "");
    await staffPage.getByLabel("Código de 6 dígitos").fill(totp(manualKey));
    await staffPage.getByRole("button", { name: "Activar cuenta" }).click();

    const recoveryList = staffPage.getByRole("list", { name: "Códigos de recuperación" });
    await expect(recoveryList.getByRole("listitem")).toHaveCount(10);
    await expect(staffPage.getByText("Estos códigos se muestran una sola vez.")).toBeVisible();
    await expect((await new AxeBuilder({ page: staffPage }).analyze()).violations).toEqual([]);
    await staffPage.getByRole("button", { name: "Ya guardé mis códigos" }).click();
    await expect(staffPage.getByRole("heading", { name: "Cuenta activada" })).toBeVisible();
    await expect(staffPage.getByRole("img", { name: "Código QR para configurar la aplicación de autenticación" })).toHaveCount(0);
    expect(await staffContext.cookies()).toEqual([]);
    expect(await staffPage.evaluate(() => ({
      local: localStorage.length,
      session: sessionStorage.length,
    }))).toEqual({ local: 0, session: 0 });

    await staffPage.reload();
    await expect(staffPage.getByText(genericLinkMessage)).toBeVisible();
    await expect(staffPage.getByRole("list", { name: "Códigos de recuperación" })).toHaveCount(0);
    state = await loadState(request, secondAccount);
    expect(state.status).toBe("active");
    expect(state.claimKinds).toEqual(["current"]);
    expect(state.links.map(({ status }) => status)).toEqual(["expired", "consumed"]);
    expect(state.factorStatus).toBe("active");
    expect(state.activeRecoveryCodes).toBe(10);
    expect(state.activeSessions).toBe(0);
    expect(consoleErrors).toEqual([]);
    expect(await staffPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  } finally {
    await staffContext.close();
  }
});

test("T065 displays staff recovery codes once after activation and never reloads them", async ({
  browser,
  request,
}) => {
  await expect((await request.post("/__test__/staff-invitations/reset")).status()).toBe(204);
  const login = await request.post("/api/admin/sessions", {
    data: {
      email: ownerEmail,
      password: ownerPassword,
      recoveryCode: ownerRecoveryCode,
    },
  });
  expect(login.status()).toBe(200);
  const { csrfToken } = await login.json() as { csrfToken: string };
  const invitation = await request.post("/api/admin/staff-invitations", {
    data: { email: staffEmail },
    headers: {
      "X-CSRF-Token": csrfToken,
      Origin: "https://127.0.0.1:8443",
      Referer: "https://127.0.0.1:8443/admin/",
    },
  });
  expect(invitation.status()).toBe(201);
  const mail = await takeMail(request);
  expect(mail.outcome).toBe("accepted");
  const token = extractToken(mail.content);
  const accountId = await findAccount(request, staffEmail);
  const staffContext = await browser.newContext();
  const staffPage = await staffContext.newPage();
  try {
    expect(await openLink(staffPage, token)).toBe(200);
    await staffPage.getByRole("button", { name: "Continuar" }).click();
    await staffPage.getByLabel("Nueva contraseña").fill(staffPassword);
    await staffPage.getByLabel("Confirmar contraseña").fill(staffPassword);
    await staffPage.getByRole("button", { name: "Continuar" }).click();
    await staffPage.getByRole("button", { name: "Mostrar clave manual" }).click();
    const manualKey = (await staffPage.getByLabel("Clave manual de autenticación").innerText()).replaceAll(" ", "");
    await staffPage.getByLabel("Código de 6 dígitos").fill(totp(manualKey));
    await staffPage.getByRole("button", { name: "Activar cuenta" }).click();

    const recoveryList = staffPage.getByRole("list", { name: "Códigos de recuperación" });
    await expect(recoveryList.getByRole("listitem")).toHaveCount(10);
    const displayedCodes = await recoveryList.locator("code").allTextContents();
    expect(new Set(displayedCodes).size).toBe(10);
    expect(displayedCodes.every((value) => /^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}$/.test(value))).toBe(true);
    await expect(staffPage.getByText("Estos códigos se muestran una sola vez.")).toBeVisible();

    await staffPage.getByRole("button", { name: "Ya guardé mis códigos" }).click();
    await expect(staffPage.getByRole("heading", { name: "Cuenta activada" })).toBeVisible();
    await expect(recoveryList).toHaveCount(0);
    await staffPage.reload();
    await expect(staffPage.getByText(genericLinkMessage)).toBeVisible();
    await expect(staffPage.getByRole("list", { name: "Códigos de recuperación" })).toHaveCount(0);
    expect(await staffContext.cookies()).toEqual([]);
    const state = await loadState(request, accountId);
    expect(state.status).toBe("active");
    expect(state.activeRecoveryCodes).toBe(10);
    expect(state.activeSessions).toBe(0);
  } finally {
    await staffContext.close();
  }
});

test("T078 consumes a recovery code once and accepts each current TOTP period once", async ({
  page,
  request,
}) => {
  await expect((await request.post("/__test__/staff-invitations/reset")).status()).toBe(204);
  const ownerAccountId = await findAccount(request, ownerEmail);

  await page.goto("/admin/");
  await page.getByLabel("Correo electrónico").fill(ownerEmail);
  await page.getByLabel("Contraseña").fill(ownerPassword);
  await page.getByRole("button", { name: "Usar un código de recuperación" }).click();
  await page.getByLabel("Código de recuperación").fill(ownerRecoveryCode);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  let ownerState = await loadState(request, ownerAccountId);
  expect(ownerState.activeRecoveryCodes).toBe(0);
  expect(ownerState.activeSessions).toBe(1);

  await page.getByRole("button", { name: "Cerrar sesión" }).click();
  await expect(page.getByText("Tu sesión terminó. Inicia sesión nuevamente.")).toBeVisible();
  await page.getByLabel("Correo electrónico").fill(ownerEmail);
  await page.getByLabel("Contraseña").fill(ownerPassword);
  await page.getByRole("button", { name: "Usar un código de recuperación" }).click();
  await page.getByLabel("Código de recuperación").fill(ownerRecoveryCode);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Las credenciales no son válidas. Revisa los datos e inténtalo de nuevo.")).toBeVisible();
  ownerState = await loadState(request, ownerAccountId);
  expect(ownerState.activeRecoveryCodes).toBe(0);
  expect(ownerState.activeSessions).toBe(0);

  await page.getByRole("button", { name: "Usar código de verificación en su lugar" }).click();
  await page.getByLabel("Contraseña").fill(ownerPassword);
  const totpCode = totp(ownerTotpSecret);
  await page.getByLabel("Código de 6 dígitos").fill(totpCode);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  ownerState = await loadState(request, ownerAccountId);
  expect(ownerState.activeSessions).toBe(1);
  expect(ownerState.activeRecoveryCodes).toBe(0);

  await page.getByRole("button", { name: "Cerrar sesión" }).click();
  await expect(page.getByText("Tu sesión terminó. Inicia sesión nuevamente.")).toBeVisible();
  await page.getByLabel("Correo electrónico").fill(ownerEmail);
  await page.getByLabel("Contraseña").fill(ownerPassword);
  await page.getByLabel("Código de 6 dígitos").fill(totpCode);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Las credenciales no son válidas. Revisa los datos e inténtalo de nuevo.")).toBeVisible();
  ownerState = await loadState(request, ownerAccountId);
  expect(ownerState.activeSessions).toBe(0);
  expect(ownerState.activeRecoveryCodes).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

async function takeMail(request: APIRequestContext): Promise<Mail> {
  await expect.poll(async () => {
    const response = await request.get("/__test__/staff-invitations/mailbox/peek");
    if (!response.ok()) return null;
    return response.json();
  }).not.toBeNull();
  const response = await request.post("/__test__/staff-invitations/mailbox/consume");
  if (!response.ok()) throw new Error("test mailbox did not contain the expected message");
  return response.json();
}

async function findAccount(request: APIRequestContext, email: string): Promise<number> {
  const response = await request.get("/__test__/staff-invitations/accounts/by-email", {
    params: { email },
  });
  if (!response.ok()) throw new Error("test staff account was not created");
  const payload = await response.json() as { accountId: number };
  return payload.accountId;
}

async function loadState(request: APIRequestContext, accountId: number): Promise<AccountState> {
  const response = await request.get(`/__test__/staff-invitations/accounts/${accountId}`);
  if (!response.ok()) throw new Error("test account state was unavailable");
  return response.json();
}

function extractToken(content: string): string {
  const match = /#token=([A-Za-z0-9_-]{43})/.exec(content);
  if (match === null) throw new Error("test email did not contain an invitation link");
  return match[1];
}

async function openLink(page: Page, token: string): Promise<number> {
  await page.goto("/admin/");
  const prepareResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/admin/staff-security-links/prepare"),
  );
  await page.goto(`/admin/staff-activation#token=${token}`);
  return (await prepareResponse).status();
}

function lifetimeSeconds(link: AccountState["links"][number]): number {
  return (Date.parse(link.expiresAt) - Date.parse(link.issuedAt)) / 1000;
}

function totp(base32Secret: string): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const character of base32Secret.replaceAll("=", "").toUpperCase()) {
    const value = alphabet.indexOf(character);
    if (value < 0) throw new Error("test TOTP key was invalid");
    bits += value.toString(2).padStart(5, "0");
  }
  const secret = Buffer.from(bits.match(/.{8}/g)?.map((byte) => parseInt(byte, 2)) ?? []);
  const counter = BigInt(Math.floor(Date.now() / 30_000));
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(counter);
  const digest = createHmac("sha1", secret).update(message).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(binary % 1_000_000).padStart(6, "0");
}
