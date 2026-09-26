import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const ownerEmail = "synthetic.owner@example.test";
const ownerPassword = "synthetic owner phrase";
const invalidMessage = "Las credenciales no son válidas. Revisa los datos e inténtalo de nuevo.";
const csrfToken = "synthetic-csrf-token";

async function fillLogin(page: Page, code = "123456") {
  await page.getByLabel("Correo electrónico").fill(ownerEmail);
  await page.getByLabel("Contraseña").fill(ownerPassword);
  await page.getByLabel("Código de 6 dígitos").fill(code);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
}

async function fulfillSession(route: Route) {
  await route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ accountId: 7, role: "owner", csrfToken }),
  });
}

async function fulfillUnauthenticated(route: Route) {
  await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
}

test("T056 shows the same Spanish error for the fifth failed login and a blocked attempt", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/admin/sessions/current", fulfillUnauthenticated);
  await page.route("**/api/admin/sessions", async (route) => {
    attempts += 1;
    expect(route.request().postDataJSON()).toEqual({
      email: ownerEmail,
      password: ownerPassword,
      totpCode: "123456",
    });
    await fulfillUnauthenticated(route);
  });

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    await fillLogin(page);
    await expect(page.getByText(invalidMessage)).toBeVisible();
    await expect(page.getByLabel("Contraseña")).toBeEmpty();
    await expect(page.getByLabel("Código de 6 dígitos")).toBeEmpty();
    await expect(page.getByText(/bloquead|existe una cuenta/i)).toHaveCount(0);
  }
  expect(attempts).toBe(6);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("T056 keeps a human action active, then presents idle and absolute expiry as a closed session", async ({ page }) => {
  let sessionActive = true;
  let invitationRequests = 0;
  let contextReads = 0;
  await page.route("**/api/admin/sessions/current", async (route) => {
    contextReads += 1;
    if (sessionActive) await fulfillSession(route);
    else await fulfillUnauthenticated(route);
  });
  await page.route("**/api/admin/staff-invitations", async (route) => {
    invitationRequests += 1;
    expect(route.request().headers()["x-csrf-token"]).toBe(csrfToken);
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ status: "pending", deliveryStatus: "accepted", detail: null }),
    });
  });

  await page.goto("/admin/");
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  await page.getByLabel("Correo del personal").fill("synthetic.staff@example.test");
  await page.getByRole("button", { name: "Enviar invitación" }).click();
  await expect(page.getByText("La invitación está pendiente y el enlace fue enviado.")).toBeVisible();
  expect(invitationRequests).toBe(1);

  // The server determines both expiration boundaries; a navigation must honor its 401.
  sessionActive = false;
  await page.reload();
  await expect(page.getByText("Tu sesión no está disponible. Inicia sesión para continuar.")).toBeVisible();
  await expect(page.getByLabel("Correo del personal")).toHaveCount(0);

  sessionActive = true;
  await page.reload();
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  sessionActive = false;
  await page.reload();
  await expect(page.getByText("Tu sesión no está disponible. Inicia sesión para continuar.")).toBeVisible();
  expect(contextReads).toBe(4);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("T056 replaces the former session and closes the new one", async ({ browser }) => {
  let activeSession = 0;
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  try {
    const first = await firstContext.newPage();
    const second = await secondContext.newPage();
    for (const [page, identity] of [[first, 1], [second, 2]] as const) {
      await page.route("**/api/admin/sessions", async (route) => {
        activeSession = identity;
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ role: "owner", csrfToken }),
        });
      });
      await page.route("**/api/admin/sessions/current", async (route) => {
        if (route.request().method() === "DELETE") {
          expect(route.request().headers()["x-csrf-token"]).toBe(csrfToken);
          activeSession = 0;
          await route.fulfill({ status: 204 });
        } else if (activeSession === identity) {
          await fulfillSession(route);
        } else {
          await fulfillUnauthenticated(route);
        }
      });
      await page.route("**/api/admin/staff-invitations", async (route) => {
        if (activeSession !== identity) await fulfillUnauthenticated(route);
        else await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ status: "pending", deliveryStatus: "accepted" }) });
      });
    }

    await first.goto("/admin/");
    await fillLogin(first);
    await expect(first.getByText("Sesión activa: propietario")).toBeVisible();
    await second.goto("/admin/");
    await fillLogin(second);
    await expect(second.getByText("Sesión activa: propietario")).toBeVisible();

    await first.getByLabel("Correo del personal").fill("synthetic.staff@example.test");
    await first.getByRole("button", { name: "Enviar invitación" }).click();
    await expect(first.getByText("Tu sesión terminó. Inicia sesión nuevamente.")).toBeVisible();
    await expect(first.getByLabel("Correo del personal")).toHaveCount(0);

    await second.getByRole("button", { name: "Cerrar sesión" }).click();
    await expect(second.getByText("Tu sesión terminó. Inicia sesión nuevamente.")).toBeVisible();
    await second.reload();
    await expect(second.getByText("Tu sesión no está disponible. Inicia sesión para continuar.")).toBeVisible();
    expect(await second.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  } finally {
    await firstContext.close();
    await secondContext.close();
  }
});
