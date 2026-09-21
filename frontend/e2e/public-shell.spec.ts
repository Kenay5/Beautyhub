import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("public reservation confirms only the submitted fictional appointment", async ({ page }) => {
  const consoleErrors: string[] = [];
  let submittedAppointment: unknown;
  let selectedStart: string | undefined;
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });

  await page.route("/api/public/services?branch=texcoco", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        { name: "Servicio sintético", duration_minutes: 60, price: "350.00" },
      ]),
    });
  });
  await page.route("/api/public/availability**", async (route) => {
    const selectedDate = new URL(route.request().url()).searchParams.get("date");
    expect(selectedDate).not.toBeNull();
    selectedStart = `${selectedDate ?? "invalid-date"}T10:00:00-06:00`;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ starts: [selectedStart, `${selectedDate ?? "invalid-date"}T10:15:00-06:00`] }),
    });
  });
  await page.route("/api/public/privacy-notice", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ version: "development-notice-test-v1", content: "Aviso ficticio de prueba." }),
    });
  });
  await page.route("/api/public/booking-confirmation-references", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({ confirmationReference: "reference-for-test-only", expiresAt: "2030-06-16T10:00:00-06:00" }),
    });
  });
  await page.route("/api/public/appointments", async (route) => {
    submittedAppointment = route.request().postDataJSON();
    const appointmentRequest = submittedAppointment as { scheduledStart: string };
    await route.fulfill({
      contentType: "application/json",
      status: 201,
      body: JSON.stringify({
        privateCode: "private-code-for-test-only",
        appointment: {
          serviceName: "Servicio sintético",
          branch: "texcoco",
          scheduledStart: appointmentRequest.scheduledStart,
          durationMinutes: 60,
          price: "350.00",
          status: "scheduled",
        },
        notifications: [
          { channel: "email", status: "accepted" },
          { channel: "whatsapp", status: "accepted" },
        ],
      }),
    });
  });

  const response = await page.goto("/");

  expect(response?.ok()).toBe(true);
  await expect(page).toHaveTitle("Manita de Gato | Salón de belleza");
  await expect(
    page.getByRole("heading", { level: 1, name: "Tu belleza en buenas manos" }),
  ).toBeVisible();

  const texcoco = page.getByRole("radio", { name: /Texcoco/ });
  await texcoco.focus();
  await page.keyboard.press("Space");
  await expect(texcoco).toBeChecked();
  await expect(page.getByText("Servicio sintético", { exact: true })).toBeVisible();
  const service = page.getByRole("radio", { name: /Servicio sintético/ });
  await service.focus();
  await page.keyboard.press("Space");
  await expect(service).toBeChecked();
  await expect(page.getByText("Seleccionado", { exact: true })).toBeVisible();
  const date = page.locator('[role="gridcell"]:not([disabled])').first();
  await date.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("radio", { name: /10:00/ })).toBeVisible();
  const start = page.getByRole("radio", { name: /10:00/ });
  await start.focus();
  await page.keyboard.press("Space");
  await expect(start).toBeChecked();
  await expect(page.locator('input[name="service"][type="text"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Continuar", exact: true }).click();
  await page.getByLabel("Nombre", { exact: true }).fill("Ana");
  await page.getByLabel("Apellido", { exact: true }).fill("López");
  await page.getByLabel("Número telefónico", { exact: true }).fill("55 1234 5678");
  await page.getByLabel("Correo electrónico", { exact: true }).fill("ana@example.com");
  await page.getByLabel("Acepto el aviso de privacidad vigente.", { exact: true }).check();
  await page.getByLabel(/Autorizo el uso de mis datos/).check();
  await page.getByLabel(/Declaro que soy una persona adulta/).check();
  await page.getByRole("button", { name: "Continuar a confirmación" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Confirma tu cita" })).toBeVisible();
  await page.getByRole("button", { name: "Confirmar mi cita" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "¡Tu cita ha sido reservada!" })).toBeVisible();
  await expect(page.getByLabel("Código privado")).toHaveText("private-code-for-test-only");
  expect(submittedAppointment).toEqual({
    confirmationReference: "reference-for-test-only",
    firstName: "Ana",
    lastName: "López",
    phone: "55 1234 5678",
    email: "ana@example.com",
    serviceName: "Servicio sintético",
    branch: "texcoco",
    scheduledStart: selectedStart,
    privacyConsent: {
      noticeVersion: "development-notice-test-v1",
      privacyNoticeAccepted: true,
      contactProcessingAuthorized: true,
      adultResponsibilityDeclared: true,
    },
  });
  const summary = page.locator(".success-details");
  await expect(summary).toContainText("Servicio sintético");
  await expect(summary).toContainText("Texcoco");
  await expect(summary).toContainText("1 hora");
  await expect(summary).toContainText("$350.00 MXN");
  await expect(page.getByText("WhatsApp: Aceptada por el proveedor")).toBeVisible();
  await expect(page.getByText("Ana", { exact: true })).toHaveCount(0);
  await expect(page.getByText("López", { exact: true })).toHaveCount(0);
  await expect(page.getByText("55 1234 5678", { exact: true })).toHaveCount(0);
  await expect(page.getByText("ana@example.com", { exact: true })).toHaveCount(0);

  const pageDimensions = await page.evaluate(() => ({
    contentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(pageDimensions.contentWidth).toBeLessThanOrEqual(
    pageDimensions.viewportWidth,
  );

  const accessibilityResults = await new AxeBuilder({ page }).analyze();
  expect(accessibilityResults.violations).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
