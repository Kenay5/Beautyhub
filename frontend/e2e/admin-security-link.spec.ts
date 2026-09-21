import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8";
const provisioningUri = "otpauth://totp/BeautyHub:admin.invalid?secret=JBSWY3DPEHPK3PXP&issuer=BeautyHub";
const recoveryCodes = Array.from(
  "RSTUVWXYZ2",
  (character) => `ABCD-EFGH-JKLM-NPQ${character}`,
);

test("T028 keeps the token in the fragment and POST body, renders QR locally, and clears browser state", async ({ page }) => {
  const prepareRequests: Array<{ body: unknown; referer: string | undefined }> = [];
  const abandonRequests: unknown[] = [];
  await page.route("**/api/admin/security-links/prepare", async (route) => {
    const request = route.request();
    prepareRequests.push({ body: request.postDataJSON(), referer: request.headers()["referer"] });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ totpSetup: { provisioningUri, manualKey: "JBSW Y3DP EHPK 3PXP" } }),
    });
  });
  await page.route("**/api/admin/security-links/abandon", async (route) => {
    abandonRequests.push(route.request().postDataJSON());
    await route.fulfill({ status: 204 });
  });

  await page.goto(`/admin/security-link#token=${token}`);

  await expect(page).toHaveURL(/\/admin\/security-link$/);
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByLabel("Nueva contraseña").fill("frase sintética segura");
  await page.getByLabel("Confirmar contraseña").fill("frase sintética segura");
  await page.getByRole("button", { name: "Continuar" }).click();
  await expect(page.getByRole("img", { name: "Código QR para configurar la aplicación de autenticación" })).toBeVisible();
  expect(prepareRequests.length).toBeGreaterThan(0);
  expect(prepareRequests.every((request) => JSON.stringify(request.body) === JSON.stringify({ token }))).toBe(true);
  expect(prepareRequests.every((request) => request.referer === undefined)).toBe(true);
  expect(await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }))).toEqual({ local: {}, session: {} });
  const requestCountBeforeLeaving = prepareRequests.length;

  await page.getByRole("link", { name: "Salir del flujo seguro" }).click();
  await expect(page).toHaveURL(/\/admin\/$/);
  expect(abandonRequests).toEqual([{ token }]);
  await expect(page.getByRole("img", { name: "Código QR para configurar la aplicación de autenticación" })).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL(/\/admin\/security-link$/);
  await expect(page.getByRole("alert")).toHaveText("Este enlace no es válido o ya no está disponible.");
  await expect(page.getByRole("img", { name: "Código QR para configurar la aplicación de autenticación" })).toHaveCount(0);
  expect(prepareRequests).toHaveLength(requestCountBeforeLeaving);
});

test("T041 keeps owner registration protected and activates without a session", async ({ page }) => {
  const completionRequests: Array<{ body: unknown; referer: string | undefined }> = [];
  await page.route("**/api/admin/security-links/prepare", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ totpSetup: { provisioningUri, manualKey: "JBSWY3DPEHPK3PXP" } }),
    });
  });
  await page.route("**/api/admin/security-links/complete", async (route) => {
    const request = route.request();
    completionRequests.push({ body: request.postDataJSON(), referer: request.headers()["referer"] });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ recoveryCodes }),
    });
  });

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Administración" })).toBeVisible();
  await expect(page.getByText(/registrar|crear cuenta/i)).toHaveCount(0);

  await page.goto(`/admin/security-link#token=${token}`);
  await expect(page.getByRole("heading", { name: "Activa tu cuenta" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Progreso de activación" })).toBeVisible();

  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByLabel("Nueva contraseña").fill("            ");
  await page.getByLabel("Confirmar contraseña").fill("            ");
  await page.getByRole("button", { name: "Continuar" }).click();
  await expect(page.getByRole("alert")).toContainText("no puede estar formada solo por espacios");
  await page.getByLabel("Nueva contraseña").fill("solo espacios no");
  await page.getByLabel("Confirmar contraseña").fill("no coincide aquí");
  await page.getByRole("button", { name: "Continuar" }).click();
  await expect(page.getByRole("alert")).toHaveText("Las contraseñas no coinciden.");

  await page.getByLabel("Nueva contraseña").fill("frase sintética segura");
  await page.getByLabel("Confirmar contraseña").fill("frase sintética segura");
  await page.getByRole("button", { name: "Continuar" }).click();
  await expect(page.getByRole("heading", { name: "Protege tu cuenta" })).toBeVisible();
  await expect(page.getByText("JBSW Y3DP EHPK 3PXP")).toHaveCount(0);
  await page.getByRole("button", { name: "Mostrar clave manual" }).click();
  await expect(page.getByText("JBSW Y3DP EHPK 3PXP")).toBeVisible();
  await page.getByLabel("Código de 6 dígitos").fill("123456");
  await page.getByRole("button", { name: "Activar cuenta" }).click();
  await expect(page.getByRole("heading", { name: "Guarda tus códigos de recuperación" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Códigos de recuperación" }).getByRole("listitem")).toHaveCount(10);
  await expect(page.getByRole("list", { name: "Códigos de recuperación" }).getByText(/^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}$/)).toHaveCount(10);
  expect(completionRequests).toEqual([{
    body: { token, password: "frase sintética segura", totpCode: "123456" },
    referer: undefined,
  }]);
  await expect(page.getByText("JBSW Y3DP EHPK 3PXP")).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("button", { name: "Ya guardé mis códigos" }).click();
  await expect(page.getByRole("heading", { name: "Cuenta activada" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Códigos de recuperación" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Ir al inicio de sesión" })).toBeVisible();

  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect(await page.context().cookies()).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.reload();
  await expect(page.getByRole("alert")).toHaveText("Este enlace no es válido o ya no está disponible.");
  await expect(page.getByRole("list", { name: "Códigos de recuperación" })).toHaveCount(0);
  await expect(page.getByText("JBSW Y3DP EHPK 3PXP")).toHaveCount(0);
});

test("T028 uses one generic message for absent or malformed link tokens", async ({ page }) => {
  let prepareCalls = 0;
  await page.route("**/api/admin/security-links/prepare", async (route) => {
    prepareCalls += 1;
    await route.fulfill({ status: 404, body: "{}" });
  });

  await page.goto("/admin/security-link#token=invalid");

  await expect(page).toHaveURL(/\/admin\/security-link$/);
  await expect(page.getByRole("alert")).toHaveText("Este enlace no es válido o ya no está disponible.");
  expect(prepareCalls).toBe(0);
});

test("T028 keeps rejected links generic after a valid-looking token is inspected", async ({ page }) => {
  await page.route("**/api/admin/security-links/prepare", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "synthetic internal link state" }),
    });
  });

  await page.goto(`/admin/security-link#token=${token}`);

  await expect(page).toHaveURL(/\/admin\/security-link$/);
  await expect(page.getByRole("alert")).toHaveText("Este enlace no es válido o ya no está disponible.");
  await expect(page.getByText("synthetic internal link state")).toHaveCount(0);
});

for (const rejectedInvitation of [
  "invitation_used",
  "invitation_cancelled",
  "invitation_replaced",
  "invitation_expired",
]) {
  test(`T039 renders the same generic message for ${rejectedInvitation}`, async ({ page }) => {
    await page.route("**/api/admin/security-links/prepare", async (route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: rejectedInvitation }),
      });
    });

    await page.goto(`/admin/security-link#token=${token}`);

    await expect(page).toHaveURL(/\/admin\/security-link$/);
    await expect(page.getByRole("alert")).toHaveText("Este enlace no es válido o ya no está disponible.");
    await expect(page.getByText(rejectedInvitation)).toHaveCount(0);
  });
}
