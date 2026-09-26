import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8";
const provisioningUri = "otpauth://totp/BeautyHub:admin.invalid?secret=JBSWY3DPEHPK3PXP&issuer=BeautyHub";
const recoveryCodes = Array.from("RSTUVWXYZ2", (character) => `ABCD-EFGH-JKLM-NPQ${character}`);

test("T070 confirms a lost-factor replacement without retaining the link or opening a session", async ({ page }) => {
  const requests: Array<{ path: string; body: unknown; referer: string | undefined }> = [];
  await page.route("**/api/admin/totp-replacement/prepare-lost", async (route) => {
    requests.push({ path: "prepare", body: route.request().postDataJSON(), referer: route.request().headers().referer });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ totpSetup: { provisioningUri, manualKey: "JBSW Y3DP EHPK 3PXP" } }),
    });
  });
  await page.route("**/api/admin/totp-replacement/complete-lost", async (route) => {
    requests.push({ path: "complete", body: route.request().postDataJSON(), referer: route.request().headers().referer });
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ recoveryCodes }) });
  });

  await page.goto(`/admin/totp-replacement#token=${token}`);

  await expect(page).toHaveURL(/\/admin\/totp-replacement$/);
  await expect(page.getByRole("img", { name: "Código QR para configurar la verificación en dos pasos" })).toBeVisible();
  await page.getByRole("button", { name: "No puedo escanear el código" }).click();
  await expect(page.getByLabel("Clave manual")).toHaveText("JBSW Y3DP EHPK 3PXP");
  await page.getByLabel("Código de verificación").fill("123456");
  await page.getByRole("button", { name: "Confirmar nuevo factor" }).click();

  await expect(page.getByRole("heading", { name: "Guarda tus códigos de recuperación" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Códigos de recuperación" }).getByRole("listitem")).toHaveCount(10);
  expect(requests).toEqual([
    { path: "prepare", body: { token }, referer: undefined },
    { path: "complete", body: { token, totpCode: "123456" }, referer: undefined },
  ]);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect(await page.context().cookies()).toEqual([]);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.reload();
  await expect(page.getByRole("alert")).toHaveText("Este enlace o configuración no está disponible.");
  await expect(page.getByRole("list", { name: "Códigos de recuperación" })).toHaveCount(0);
});


test("T070 discards the pending QR and hides all setup data when lost-factor confirmation fails", async ({ page }) => {
  await page.route("**/api/admin/totp-replacement/prepare-lost", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ totpSetup: { provisioningUri, manualKey: "JBSW Y3DP EHPK 3PXP" } }),
    });
  });
  await page.route("**/api/admin/totp-replacement/complete-lost", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ token, totpCode: "000000" });
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "synthetic internal link or factor state" }),
    });
  });

  await page.goto(`/admin/totp-replacement#token=${token}`);
  await expect(page.getByRole("img", { name: "Código QR para configurar la verificación en dos pasos" })).toBeVisible();
  await page.getByLabel("Código de verificación").fill("000000");
  await page.getByRole("button", { name: "Confirmar nuevo factor" }).click();

  await expect(page.getByRole("alert")).toHaveText("Este enlace o configuración no está disponible.");
  await expect(page.getByRole("img", { name: "Código QR para configurar la verificación en dos pasos" })).toHaveCount(0);
  await expect(page.getByText("JBSW Y3DP EHPK 3PXP")).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Códigos de recuperación" })).toHaveCount(0);
  await expect(page.getByText("synthetic internal link or factor state")).toHaveCount(0);
  expect(await page.evaluate(() => ({
    local: localStorage.length,
    session: sessionStorage.length,
    noOverflow: document.documentElement.scrollWidth <= innerWidth,
  }))).toEqual({ local: 0, session: 0, noOverflow: true });
  expect(await page.context().cookies()).toEqual([]);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
