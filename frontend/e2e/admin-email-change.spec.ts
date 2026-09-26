import { createHmac } from "node:crypto";
import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const ownerEmail = "synthetic.owner@example.test";
const ownerPassword = "synthetic owner phrase for browser tests";
const ownerRecoveryCode = "ABCD-EFGH-JKLM-NPQR";
const ownerTotpSecret = "JBSWY3DPEHPK3PXP";

type Mail = { outcome: "accepted" | "failed"; recipient: string; content: string };
type EmailChangeState = {
  status: string;
  claims: Array<{ kind: string; email: string }>;
  links: Array<{
    status: string;
    deliveryStatus: string;
    issuedAt: string;
    expiresAt: string;
  }>;
  activeSessions: number;
};

test("T079 requests, replaces, and confirms an email change through PostgreSQL", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  await reset(request);
  const accountId = await findOwner(request);
  const unauthenticated = await request.post("/api/admin/account/email-change", {
    data: {
      newEmail: "synthetic.unauthorized@example.test",
      currentPassword: ownerPassword,
      totpCode: totp(ownerTotpSecret),
      accountId,
    },
  });
  expect(unauthenticated.status()).toBe(401);
  expect((await unauthenticated.json()).detail).toBe("Autenticación administrativa requerida.");
  expect(JSON.stringify(await unauthenticated.json())).not.toContain("synthetic.owner");
  expect((await loadState(request, accountId)).claims).toEqual([
    { kind: "current", email: ownerEmail },
  ]);

  await signIn(page);
  const panel = page.getByRole("region", { name: "Solicitar cambio de correo" });
  await expect(panel.getByText("Tu correo actual no cambiará durante esta solicitud.")).toBeVisible();
  await expect(panel.getByLabel("Correo nuevo")).toBeVisible();
  await expect(panel.getByLabel("Contraseña actual")).toBeVisible();
  await expect(panel.getByLabel("Código de 6 dígitos")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).include(".staff-access-card").analyze()).violations).toEqual([]);

  const viewport = test.info().project.use.viewport;
  if (viewport?.width === 320 || viewport?.width === 1280) {
    const evidenceDirectory = join(tmpdir(), "beautyhub-t079-visual-review");
    mkdirSync(evidenceDirectory, { recursive: true });
    await page.screenshot({ path: join(evidenceDirectory, `${test.info().project.name}.png`), fullPage: true });
  }

  const firstPeriod = await submitChange(page, "synthetic.first@example.test", ownerTotpSecret);
  await expect(page.getByRole("status")).toContainText("Tu correo actual sigue activo hasta entonces.");
  const firstMail = await takeMail(request);
  expect(firstMail.outcome).toBe("accepted");
  expect(firstMail.recipient).toBe("synthetic.first@example.test");
  const firstToken = extractToken(firstMail.content);
  const firstState = await loadState(request, accountId);
  expect(firstState.claims).toEqual([
    { kind: "current", email: ownerEmail },
    { kind: "reserved", email: "synthetic.first@example.test" },
  ]);
  expect(firstState.links.map(({ status, deliveryStatus }) => [status, deliveryStatus])).toEqual([
    ["active", "accepted"],
  ]);
  expect(lifetimeSeconds(firstState.links[0])).toBe(30 * 60);
  expect(firstState.activeSessions).toBe(1);

  await submitChange(page, "synthetic.second@example.test", ownerTotpSecret, firstPeriod);
  await expect(page.getByRole("status")).toContainText("Tu correo actual sigue activo hasta entonces.");
  const secondMail = await takeMail(request);
  expect(secondMail.outcome).toBe("accepted");
  expect(secondMail.recipient).toBe("synthetic.second@example.test");
  const secondToken = extractToken(secondMail.content);
  expect(secondToken).not.toBe(firstToken);
  const replacedState = await loadState(request, accountId);
  expect(replacedState.claims).toEqual([
    { kind: "current", email: ownerEmail },
    { kind: "reserved", email: "synthetic.second@example.test" },
  ]);
  expect(replacedState.links.map(({ status, deliveryStatus }) => [status, deliveryStatus])).toEqual([
    ["invalidated", "accepted"],
    ["active", "accepted"],
  ]);
  expect(replacedState.links.filter(({ status }) => status === "active")).toHaveLength(1);

  await expectConfirmationFailure(page, firstToken);
  await expectConfirmationSuccess(page, secondToken);
  const completedState = await loadState(request, accountId);
  expect(completedState.claims).toEqual([
    { kind: "current", email: "synthetic.second@example.test" },
  ]);
  expect(completedState.links.map(({ status }) => status)).toEqual(["invalidated", "consumed"]);
  expect(completedState.activeSessions).toBe(0);

  const oldAddressNotice = await takeMail(request);
  const newAddressNotice = await takeMail(request);
  expect([oldAddressNotice, newAddressNotice].map(({ outcome, recipient }) => [outcome, recipient])).toEqual([
    ["accepted", ownerEmail],
    ["accepted", "synthetic.second@example.test"],
  ]);
  for (const notice of [oldAddressNotice, newAddressNotice]) {
    expect(notice.content).not.toContain("#token=");
    expect(notice.content).not.toContain(ownerPassword);
  }
  expect(await mailboxIsEmpty(request)).toBe(true);
  expect((await request.get("/api/admin/sessions/current")).status()).toBe(401);
});

test("T079 expired confirmation preserves the current email and releases the reservation", async ({
  page,
  request,
}) => {
  await reset(request);
  const accountId = await findOwner(request);
  await signIn(page);
  await submitChange(page, "synthetic.expired@example.test", ownerTotpSecret);
  const mail = await takeMail(request);
  const token = extractToken(mail.content);
  expect((await request.post("/__test__/email-changes/expire", { data: { token } })).status()).toBe(204);

  await expectConfirmationFailure(page, token);
  const state = await loadState(request, accountId);
  expect(state.claims).toEqual([{ kind: "current", email: ownerEmail }]);
  expect(state.links.map(({ status }) => status)).toEqual(["expired"]);
  expect(state.activeSessions).toBe(1);
  expect(await mailboxIsEmpty(request)).toBe(true);
});

test("T079 delivery rejection invalidates the link and leaves the previous email active", async ({
  page,
  request,
}) => {
  await reset(request);
  const accountId = await findOwner(request);
  await request.put("/__test__/email-changes/mailbox/outcome", { data: { outcome: "failed" } });
  await signIn(page);
  await submitChange(page, "synthetic.rejected@example.test", ownerTotpSecret);
  await expect(page.getByRole("status")).toContainText("No se pudo enviar el enlace.");
  const failedMail = await takeMail(request);
  expect(failedMail.outcome).toBe("failed");
  const state = await loadState(request, accountId);
  expect(state.claims).toEqual([{ kind: "current", email: ownerEmail }]);
  expect(state.links.map(({ status, deliveryStatus }) => [status, deliveryStatus])).toEqual([
    ["invalidated", "failed"],
  ]);
  await expectConfirmationFailure(page, extractToken(failedMail.content));
  expect((await loadState(request, accountId)).claims).toEqual([
    { kind: "current", email: ownerEmail },
  ]);
});

async function reset(request: APIRequestContext): Promise<void> {
  expect((await request.post("/__test__/email-changes/reset")).status()).toBe(204);
}

async function findOwner(request: APIRequestContext): Promise<number> {
  const response = await request.get("/__test__/email-changes/accounts/by-email", {
    params: { email: ownerEmail },
  });
  expect(response.status()).toBe(200);
  return (await response.json() as { accountId: number }).accountId;
}

async function loadState(request: APIRequestContext, accountId: number): Promise<EmailChangeState> {
  const response = await request.get(`/__test__/email-changes/accounts/${accountId}`);
  expect(response.status()).toBe(200);
  return response.json();
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  await page.getByLabel("Correo electrónico").fill(ownerEmail);
  await page.getByLabel("Contraseña").fill(ownerPassword);
  await page.getByRole("button", { name: "Usar un código de recuperación" }).click();
  await page.getByLabel("Código de recuperación").fill(ownerRecoveryCode);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
}

async function submitChange(
  page: Page,
  email: string,
  secret: string,
  afterPeriod?: number,
): Promise<number> {
  const panel = page.getByRole("region", { name: "Solicitar cambio de correo" });
  await panel.getByLabel("Correo nuevo").fill(email);
  await panel.getByLabel("Contraseña actual").fill(ownerPassword);
  if (afterPeriod !== undefined) await waitForNextTotpPeriod(afterPeriod);
  else await avoidTotpBoundary();
  const currentPeriod = Math.floor(Date.now() / 30_000);
  await panel.getByLabel("Código de 6 dígitos").fill(totp(secret));
  await panel.getByRole("button", { name: "Reservar correo" }).click();
  return currentPeriod;
}

async function waitForNextTotpPeriod(period: number): Promise<void> {
  await expect.poll(async () => Math.floor(Date.now() / 30_000), { timeout: 35_000 }).toBeGreaterThan(period);
  await new Promise((resolve) => setTimeout(resolve, 1_000));
}

async function avoidTotpBoundary(): Promise<void> {
  const remainingMs = 30_000 - (Date.now() % 30_000);
  if (remainingMs < 5_000) await waitForNextTotpPeriod(Math.floor(Date.now() / 30_000));
  else await new Promise((resolve) => setTimeout(resolve, 250));
}

async function takeMail(request: APIRequestContext): Promise<Mail> {
  await expect.poll(async () => {
    const response = await request.get("/__test__/staff-invitations/mailbox/peek");
    return response.ok() ? response.json() : null;
  }).not.toBeNull();
  const response = await request.post("/__test__/staff-invitations/mailbox/consume");
  expect(response.status()).toBe(200);
  return response.json();
}

async function mailboxIsEmpty(request: APIRequestContext): Promise<boolean> {
  const response = await request.get("/__test__/staff-invitations/mailbox/peek");
  return response.ok() && (await response.json()) === null;
}

async function expectConfirmationFailure(page: Page, token: string): Promise<void> {
  await page.goto("/admin/");
  await page.goto(`/admin/email-change#token=${token}`);
  await expect(page).toHaveURL(/\/admin\/email-change$/);
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/admin/account/email-change/complete"),
  );
  await page.getByRole("button", { name: "Confirmar cambio de correo" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "No fue posible confirmar el cambio" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Tu correo anterior permanece activo");
}

async function expectConfirmationSuccess(page: Page, token: string): Promise<void> {
  await page.goto("/admin/");
  await page.goto(`/admin/email-change#token=${token}`);
  await expect(page).toHaveURL(/\/admin\/email-change$/);
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/admin/account/email-change/complete"),
  );
  await page.getByRole("button", { name: "Confirmar cambio de correo" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(204);
  await expect(page.getByRole("heading", { name: "Correo cambiado" })).toBeVisible();
  expect((await page.request.get("/api/admin/sessions/current")).status()).toBe(401);
}

function extractToken(content: string): string {
  const match = /#token=([A-Za-z0-9_-]{43})/.exec(content);
  if (match === null) throw new Error("test email did not contain an email-change link");
  return match[1];
}

function lifetimeSeconds(link: EmailChangeState["links"][number]): number {
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
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", secret).update(message).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(binary % 1_000_000).padStart(6, "0");
}
