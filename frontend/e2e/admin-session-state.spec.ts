import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";


const csrfToken = "fresh-csrf-token";


test("T054 keeps credentials in memory and reacts to login and logout in Spanish", async ({ page }) => {
  let contextRequests = 0;
  let loginBody: unknown;
  let logoutCsrf: string | undefined;

  await page.route("**/api/admin/sessions/current", async (route) => {
    if (route.request().method() === "DELETE") {
      logoutCsrf = route.request().headers()["x-csrf-token"];
      await route.fulfill({ status: 204 });
      return;
    }
    contextRequests += 1;
    if (contextRequests === 1) {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Autenticación administrativa requerida." }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 7, role: "owner", csrfToken }),
    });
  });
  await page.route("**/api/admin/sessions", async (route) => {
    loginBody = route.request().postDataJSON();
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ role: "owner", csrfToken: "initial-csrf-token" }),
    });
  });

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  await page.getByLabel("Correo electrónico").fill("synthetic.owner@example.test");
  await page.getByLabel("Contraseña").fill("synthetic owner phrase");
  await page.getByLabel("Código de 6 dígitos").fill("123456");
  await page.getByRole("button", { name: "Iniciar sesión" }).click();

  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  expect(loginBody).toEqual({
    email: "synthetic.owner@example.test",
    password: "synthetic owner phrase",
    totpCode: "123456",
  });
  expect(
    await page.evaluate(() => ({
      local: localStorage.length,
      session: sessionStorage.length,
    })),
  ).toEqual({ local: 0, session: 0 });

  await page.getByRole("button", { name: "Cerrar sesión" }).click();
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  await expect(page.getByText("Tu sesión terminó. Inicia sesión nuevamente.")).toBeVisible();
  expect(logoutCsrf).toBe(csrfToken);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});


test("T054 treats a backend 401 as session loss without exposing private state", async ({ page }) => {
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 8, role: "owner", csrfToken }),
    });
  });
  await page.route("**/api/admin/staff-invitations", async (route) => {
    await route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Autenticación administrativa requerida." }),
    });
  });

  const response = await page.goto("/admin/");
  expect(response?.headers()["cache-control"]).toBe("no-store");
  expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
  expect(response?.headers()["x-frame-options"]).toBe("DENY");
  expect(response?.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");

  await page.getByLabel("Correo del personal").fill("synthetic.staff@example.test");
  await page.getByRole("button", { name: "Enviar invitación" }).click();
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  await expect(page.getByText("Tu sesión terminó. Inicia sesión nuevamente.")).toBeVisible();
  await expect(page.getByLabel("Correo del personal")).toHaveCount(0);
});
