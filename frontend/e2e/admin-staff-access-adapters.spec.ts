import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";


const token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8";
const csrfToken = "synthetic-csrf-token";
const recoveryCodes = Array.from("RSTUVWXYZ2", (value) => `ABCD-EFGH-JKLM-NPQ${value}`);


test("T035-T037 exposes the minimum owner invitation interface and safe delivery states", async ({ page }) => {
  const requests: Array<{ path: string; body: unknown; csrf: string | undefined }> = [];
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 7, role: "owner", csrfToken }),
    });
  });
  await page.route("**/api/admin/staff-invitations", async (route) => {
    requests.push({
      path: "invite",
      body: route.request().postDataJSON(),
      csrf: route.request().headers()["x-csrf-token"],
    });
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        status: "pending",
        deliveryStatus: "failed",
        detail: "No se pudo enviar el correo. Inténtalo de nuevo.",
      }),
    });
  });
  await page.route("**/api/admin/staff-invitations/resend", async (route) => {
    requests.push({
      path: "resend",
      body: route.request().postData(),
      csrf: route.request().headers()["x-csrf-token"],
    });
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ status: "pending", deliveryStatus: "accepted", detail: null }),
    });
  });
  await page.route("**/api/admin/staff-invitations/cancel", async (route) => {
    requests.push({
      path: "cancel",
      body: route.request().postData(),
      csrf: route.request().headers()["x-csrf-token"],
    });
    await route.fulfill({ status: 204 });
  });

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Administración" })).toBeVisible();
  await page.getByLabel("Correo del personal").fill("synthetic.staff@example.test");
  await page.getByRole("button", { name: "Enviar invitación" }).click();
  await expect(page.getByText("No se pudo enviar el correo. Inténtalo de nuevo.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reenviar invitación" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar invitación" })).toBeVisible();

  await page.getByRole("button", { name: "Reenviar invitación" }).click();
  await expect(page.getByText("La invitación está pendiente y el enlace fue enviado.")).toBeVisible();
  await page.getByRole("button", { name: "Cancelar invitación" }).click();
  await expect(page.getByText("La invitación fue cancelada. Ya puedes crear una nueva.")).toBeVisible();
  await expect(page.getByLabel("Correo del personal")).toBeVisible();

  expect(requests).toEqual([
    { path: "invite", body: { email: "synthetic.staff@example.test" }, csrf: csrfToken },
    { path: "resend", body: null, csrf: csrfToken },
    { path: "cancel", body: null, csrf: csrfToken },
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});


test("T038 routes an invited staff member through their own activation endpoints", async ({ page }) => {
  const endpoints: string[] = [];
  await page.route("**/api/admin/staff-security-links/prepare", async (route) => {
    endpoints.push("prepare");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        totpSetup: {
          provisioningUri: "otpauth://totp/Manita%20de%20Gato:Personal?secret=JBSWY3DPEHPK3PXP",
          manualKey: "JBSWY3DPEHPK3PXP",
        },
      }),
    });
  });
  await page.route("**/api/admin/staff-security-links/complete", async (route) => {
    endpoints.push("complete");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ recoveryCodes }),
    });
  });

  await page.goto(`/admin/staff-activation#token=${token}`);
  await expect(page).toHaveURL(/\/admin\/staff-activation$/);
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByLabel("Nueva contraseña").fill("synthetic staff phrase");
  await page.getByLabel("Confirmar contraseña").fill("synthetic staff phrase");
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByLabel("Código de 6 dígitos").fill("123456");
  await page.getByRole("button", { name: "Activar cuenta" }).click();

  await expect(page.getByRole("list", { name: "Códigos de recuperación" }).getByRole("listitem")).toHaveCount(10);
  expect(endpoints).toEqual(["prepare", "complete"]);
  expect(await page.context().cookies()).toEqual([]);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
});
