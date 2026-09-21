import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("public lookup submits the private code only in the body and renders one safe appointment", async ({ page }) => {
  const consoleErrors: string[] = [];
  const requestUrls: string[] = [];
  const requestBodies: unknown[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.route("/api/public/appointments/lookup", async (route) => {
    requestUrls.push(route.request().url());
    requestBodies.push(route.request().postDataJSON());
    const payload = route.request().postDataJSON() as { privateCode?: string };
    if (payload.privateCode === "scheduled-private-code") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          serviceName: "Uñas acrílicas demo",
          branch: "texcoco",
          scheduledStart: "2030-06-15T10:00:00-06:00",
          durationMinutes: 90,
          price: "450.00",
          status: "scheduled",
          contact: { phone: "******5678", email: "a***@e***.com" },
        }),
      });
      return;
    }
    if (payload.privateCode === "cancelled-private-code") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          serviceName: "Cabello demo",
          branch: "chiconcuac",
          scheduledStart: "2030-06-16T12:00:00-06:00",
          durationMinutes: 60,
          price: "300.00",
          status: "cancelled",
          contact: { phone: "******4321", email: "c***@e***.com" },
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      status: 404,
      body: JSON.stringify({ detail: "No fue posible validar las credenciales de la cita." }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Consultar mi cita" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Consulta tu cita" })).toBeVisible();
  await expect(page.getByLabel("Código privado")).toBeVisible();
  await expect(page.getByLabel("Número telefónico")).toHaveCount(0);
  await expect(page.getByLabel("Correo electrónico")).toHaveCount(0);

  await page.getByLabel("Código privado").fill("scheduled-private-code");
  await page.getByRole("button", { name: "Consultar cita" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Tu cita está aquí" })).toBeVisible();
  await expect(page.getByText("Uñas acrílicas demo", { exact: true })).toBeVisible();
  await expect(page.getByText("Texcoco", { exact: true })).toBeVisible();
  await expect(page.getByText("******5678", { exact: true })).toBeVisible();
  await expect(page.getByText("a***@e***.com", { exact: true })).toBeVisible();
  await expect(page.getByText("scheduled-private-code", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Modificar cita" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar cita" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Descargar/ })).toHaveCount(0);

  expect(requestUrls[0]).not.toContain("scheduled-private-code");
  expect(new URL(requestUrls[0]).search).toBe("");
  expect(requestBodies[0]).toEqual({ privateCode: "scheduled-private-code" });

  const dimensions = await page.evaluate(() => ({
    contentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("button", { name: "Consultar otra cita" }).click();
  await page.getByLabel("Código privado").fill("cancelled-private-code");
  await page.getByRole("button", { name: "Consultar cita" }).click();
  await expect(page.getByText("Cancelada", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Modificar cita" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancelar cita" })).toHaveCount(0);

  await page.getByRole("button", { name: "Consultar otra cita" }).click();
  await page.getByLabel("Código privado").fill("invalid-private-code");
  expect(consoleErrors).toEqual([]);
  await page.getByRole("button", { name: "Consultar cita" }).click();
  await expect(page.getByRole("alert")).toHaveText("No fue posible validar las credenciales de la cita.");
  await expect(page.getByText("Cabello demo", { exact: true })).toHaveCount(0);
  expect(consoleErrors.some((message) => message.includes("invalid-private-code"))).toBe(false);
});

test("public modification asks for the registered phone and submits only approved fields", async ({ page }) => {
  const modificationBodies: unknown[] = [];
  await page.route("/api/public/appointments/lookup", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        serviceName: "Uñas acrílicas demo",
        branch: "texcoco",
        scheduledStart: "2030-06-15T10:00:00-06:00",
        durationMinutes: 90,
        price: "450.00",
        status: "scheduled",
        contact: { phone: "******5678", email: "a***@e***.com" },
      }),
    });
  });
  await page.route("/api/public/services?branch=*", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify([{ name: "Uñas acrílicas demo", duration_minutes: 90, price: "450.00" }, { name: "Pestañas demo", duration_minutes: 60, price: "350.00" }]) });
  });
  await page.route("/api/public/availability?*", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ starts: ["2030-06-16T11:00:00-06:00", "2030-06-16T11:15:00-06:00"] }) });
  });
  await page.route("/api/public/appointments/reschedule", async (route) => {
    modificationBodies.push(route.request().postDataJSON());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        appointment: { serviceName: "Pestañas demo", branch: "texcoco", scheduledStart: "2030-06-16T11:15:00-06:00", durationMinutes: 60, price: "350.00", status: "scheduled" },
        notifications: [
          { channel: "email", status: "accepted" },
          { channel: "whatsapp", status: "accepted" },
        ],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Consultar mi cita" }).click();
  await page.getByLabel("Código privado").fill("scheduled-private-code");
  await page.getByRole("button", { name: "Consultar cita" }).click();
  await page.getByRole("button", { name: "Modificar cita" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Elige los nuevos datos" })).toBeVisible();
  await expect(page.getByLabel("Número telefónico")).toBeVisible();
  await expect(page.getByLabel("Nombre")).toHaveCount(0);
  await expect(page.getByLabel("Correo electrónico")).toHaveCount(0);
  await expect(page.getByLabel("Servicio")).toBeVisible();
  const dimensions = await page.evaluate(() => ({ contentWidth: document.documentElement.scrollWidth, viewportWidth: document.documentElement.clientWidth }));
  expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByLabel("Número telefónico").fill("5512345678");
  await page.getByLabel("Servicio").selectOption("Pestañas demo");
  await page.getByLabel("Nueva fecha").fill("2030-06-16");
  await page.getByRole("radio", { name: /11:15/ }).check();
  await page.getByRole("button", { name: "Confirmar cambios" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Tu cita se actualizó" })).toBeVisible();
  await expect(page.getByText("Pestañas demo", { exact: true })).toBeVisible();
  expect(modificationBodies).toEqual([{
    privateCode: "scheduled-private-code",
    phone: "5512345678",
    serviceName: "Pestañas demo",
    branch: "texcoco",
    scheduledStart: "2030-06-16T11:15:00-06:00",
  }]);
  await expect(page.getByText("scheduled-private-code", { exact: true })).toHaveCount(0);
});

test("public cancellation confirms the safe result and approved notification channels", async ({ page }) => {
  const cancellationBodies: unknown[] = [];
  await page.route("/api/public/appointments/lookup", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ serviceName: "Uñas acrílicas demo", branch: "texcoco", scheduledStart: "2030-06-15T10:00:00-06:00", durationMinutes: 90, price: "450.00", status: "scheduled", contact: { phone: "******5678", email: "a***@e***.com" } }) });
  });
  await page.route("/api/public/appointments/cancel", async (route) => {
    cancellationBodies.push(route.request().postDataJSON());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        appointment: { serviceName: "Uñas acrílicas demo", branch: "texcoco", scheduledStart: "2030-06-15T10:00:00-06:00", durationMinutes: 90, price: "450.00", status: "cancelled" },
        notifications: [
          { channel: "email", status: "accepted" },
          { channel: "whatsapp", status: "accepted" },
        ],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Consultar mi cita" }).click();
  await page.getByLabel("Código privado").fill("scheduled-private-code");
  await page.getByRole("button", { name: "Consultar cita" }).click();
  await page.getByRole("button", { name: "Cancelar cita" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Verifiquemos tu identidad" })).toBeVisible();
  await expect(page.getByText("scheduled-private-code", { exact: true })).toHaveCount(0);
  await page.getByLabel("Número telefónico").fill("5512345678");
  await page.getByRole("button", { name: "Continuar a la cancelación" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "¿Deseas cancelar tu cita?" })).toBeVisible();
  await page.getByLabel(/Motivo de cancelación/).fill("Cambio de planes");
  await page.getByRole("button", { name: "Sí, cancelar cita" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Tu cita ha sido cancelada" })).toBeVisible();
  await expect(page.getByText("Cancelada", { exact: true })).toBeVisible();
  await expect(page.getByText("WhatsApp: Aceptado por el canal", { exact: true })).toBeVisible();
  await expect(page.getByText("Correo electrónico: Aceptado por el canal", { exact: true })).toBeVisible();
  await expect(page.getByText("scheduled-private-code", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Cambio de planes", { exact: true })).toHaveCount(0);
  expect(cancellationBodies).toEqual([{ privateCode: "scheduled-private-code", phone: "5512345678", reason: "Cambio de planes" }]);
  const dimensions = await page.evaluate(() => ({ contentWidth: document.documentElement.scrollWidth, viewportWidth: document.documentElement.clientWidth }));
  expect(dimensions.contentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
