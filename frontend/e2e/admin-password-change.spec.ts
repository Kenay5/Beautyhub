import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";


test("T057 changes a staff password after recoverable failures without browser persistence", async ({ page }) => {
  const csrfToken = "synthetic-csrf-token";
  const requests: unknown[] = [];
  const outcomes = [400, 422, 204];

  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 7, role: "staff", csrfToken }),
    });
  });
  await page.route("**/api/admin/password", async (route) => {
    requests.push({
      body: route.request().postDataJSON(),
      csrf: route.request().headers()["x-csrf-token"],
    });
    const status = outcomes.shift();
    if (status === 204) {
      await route.fulfill({ status });
    } else {
      await route.fulfill({
        status: status ?? 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "No fue posible cambiar la contraseña." }),
      });
    }
  });

  await page.goto("/admin/");
  const passwordChange = page.getByRole("region", { name: "Cambiar contraseña" });
  await expect(page.getByText("Sesión activa: personal")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cambiar contraseña" })).toBeVisible();
  await expect(passwordChange.getByLabel("Contraseña actual", { exact: true })).toHaveAttribute("autocomplete", "current-password");
  await expect(passwordChange.getByLabel("Nueva contraseña")).toHaveAttribute("autocomplete", "new-password");
  await expect(passwordChange.getByLabel("Código de 6 dígitos")).toHaveAttribute("autocomplete", "one-time-code");

  for (const [index, expectedMessage] of [
    "No fue posible comprobar las credenciales.",
    "La nueva contraseña no es válida. Usa entre 12 y 128 caracteres y evita contraseñas comunes.",
  ].entries()) {
    await passwordChange.getByLabel("Contraseña actual", { exact: true }).fill("synthetic current phrase");
    await passwordChange.getByLabel("Código de 6 dígitos").fill("123456");
    await passwordChange.getByLabel("Nueva contraseña").fill("synthetic new phrase");
    await passwordChange.getByRole("button", { name: "Cambiar contraseña" }).click();
    await expect(passwordChange.getByRole("alert")).toHaveText(expectedMessage);
    await expect(passwordChange.getByLabel("Contraseña actual", { exact: true })).toBeEmpty();
    await expect(passwordChange.getByLabel("Código de 6 dígitos")).toBeEmpty();
    await expect(passwordChange.getByLabel("Nueva contraseña")).toBeEmpty();
    await expect(page.getByText("Sesión activa: personal")).toBeVisible();
    expect(requests).toHaveLength(index + 1);
  }

  await passwordChange.getByLabel("Contraseña actual", { exact: true }).fill("synthetic current phrase");
  await passwordChange.getByLabel("Código de 6 dígitos").fill("123456");
  await passwordChange.getByLabel("Nueva contraseña").fill("synthetic new phrase");
  await passwordChange.getByRole("button", { name: "Cambiar contraseña" }).click();
  await expect(page.getByText("Tu contraseña fue actualizada. Inicia sesión nuevamente.")).toBeVisible();
  await expect(passwordChange.getByLabel("Nueva contraseña")).toHaveCount(0);

  expect(requests).toEqual(Array.from({ length: 3 }, () => ({
    body: {
      currentPassword: "synthetic current phrase",
      totpCode: "123456",
      newPassword: "synthetic new phrase",
    },
    csrf: csrfToken,
  })));
  expect(await page.evaluate(() => ({
    local: localStorage.length,
    session: sessionStorage.length,
    noOverflow: document.documentElement.scrollWidth <= innerWidth,
  }))).toEqual({ local: 0, session: 0, noOverflow: true });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});


test("T057 keeps the owner password form accessible beside invitation controls", async ({ page }) => {
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 1, role: "owner", csrfToken: "synthetic-csrf-token" }),
    });
  });

  await page.goto("/admin/");
  const passwordChange = page.getByRole("region", { name: "Cambiar contraseña" });
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  await expect(page.getByLabel("Correo del personal")).toBeVisible();
  await expect(passwordChange.getByLabel("Contraseña actual", { exact: true })).toBeVisible();
  await expect(passwordChange.getByLabel("Nueva contraseña")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});


test("T066 regenerates recovery codes once, clears credentials, and closes the session", async ({ page }) => {
  const csrfToken = "synthetic-csrf-token";
  const recoveryCodes = [
    "ABCD-EFGH-JKLM-NPQ2",
    "ABCD-EFGH-JKLM-NPQ3",
    "ABCD-EFGH-JKLM-NPQ4",
    "ABCD-EFGH-JKLM-NPQ5",
    "ABCD-EFGH-JKLM-NPQ6",
    "ABCD-EFGH-JKLM-NPQ7",
    "ABCD-EFGH-JKLM-NPQ8",
    "ABCD-EFGH-JKLM-NPQ9",
    "ABCD-EFGH-JKLM-NPQA",
    "ABCD-EFGH-JKLM-NPQB",
  ];
  const responses = [400, 400, 200];
  const requests: unknown[] = [];
  let sessionActive = true;

  await page.route("**/api/admin/sessions/current", async (route) => {
    if (sessionActive) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ accountId: 7, role: "staff", csrfToken }),
      });
    } else {
      await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
    }
  });
  await page.route("**/api/admin/recovery-codes/regenerate", async (route) => {
    const outcome = responses.shift();
    requests.push({
      body: route.request().postDataJSON(),
      csrf: route.request().headers()["x-csrf-token"],
    });
    if (outcome === 200) {
      sessionActive = false;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: {
          "set-cookie": "__Host-beautyhub-session=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Strict",
        },
        body: JSON.stringify({ recoveryCodes }),
      });
    } else {
      await route.fulfill({
        status: outcome ?? 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "No fue posible comprobar las credenciales." }),
      });
    }
  });

  await page.goto("/admin/");
  await expect(page.getByText("Sesión activa: personal")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Regenerar códigos de recuperación" })).toBeVisible();
  const password = page.getByLabel("Contraseña actual para regenerar códigos");
  const totp = page.getByLabel("Código temporal para regenerar códigos");

  for (let attempt = 0; attempt < 2; attempt += 1) {
    await password.fill("synthetic current phrase");
    await totp.fill("123456");
    await page.getByRole("button", { name: "Regenerar códigos" }).click();
    await expect(page.getByRole("alert")).toHaveText("No fue posible comprobar las credenciales.");
    await expect(password).toBeEmpty();
    await expect(totp).toBeEmpty();
    await expect(page.getByText("Sesión activa: personal")).toBeVisible();
  }

  await password.fill("synthetic current phrase");
  await totp.fill("123456");
  await page.getByRole("button", { name: "Regenerar códigos" }).click();
  await expect(page.getByRole("heading", { name: "Guarda tus nuevos códigos de recuperación" })).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveCount(10);
  await expect(page.getByText("Sesión activa: personal")).toHaveCount(0);
  expect(requests).toEqual(Array.from({ length: 3 }, () => ({
    body: {
      currentPassword: "synthetic current phrase",
      totpCode: "123456",
    },
    csrf: csrfToken,
  })));
  expect(await page.evaluate(() => ({
    local: localStorage.length,
    session: sessionStorage.length,
    noOverflow: document.documentElement.scrollWidth <= innerWidth,
  }))).toEqual({ local: 0, session: 0, noOverflow: true });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("button", { name: "Ya guardé mis códigos" }).click();
  await expect(page.getByRole("heading", { name: "Iniciar sesión" })).toBeVisible();
  await expect(page.getByText("ABCD-EFGH-JKLM-NPQ2")).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Tu sesión no está disponible. Inicia sesión para continuar.")).toBeVisible();
  await expect(page.getByText("ABCD-EFGH-JKLM-NPQ2")).toHaveCount(0);
});

test("T067 prepares a new TOTP factor with old-factor proof without closing the session", async ({ page }) => {
  const csrfToken = "synthetic-csrf-token";
  const requests: unknown[] = [];
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 7, role: "staff", csrfToken }),
    });
  });
  await page.route("**/api/admin/totp-replacement/prepare", async (route) => {
    requests.push({ body: route.request().postDataJSON(), csrf: route.request().headers()["x-csrf-token"] });
    const body = route.request().postDataJSON() as Record<string, unknown>;
    if (body.currentPassword === "bad password") {
      await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "No fue posible comprobar las credenciales." }) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "cache-control": "no-store", "referrer-policy": "no-referrer" },
      body: JSON.stringify({ provisioningUri: "otpauth://totp/BeautyHub:synthetic", manualKey: "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" }),
    });
  });

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Reemplazar aplicación de autenticación" })).toBeVisible();
  const password = page.getByLabel("Contraseña actual para reemplazar el factor");
  const code = page.getByLabel("Código temporal actual");
  await password.fill("bad password");
  await code.fill("123456");
  await page.getByRole("button", { name: "Preparar factor nuevo" }).click();
  await expect(page.getByRole("alert")).toHaveText("No fue posible comprobar las credenciales.");
  await expect(password).toBeEmpty();
  await expect(code).toBeEmpty();
  await expect(page.getByRole("img", { name: "Código QR para configurar la nueva aplicación de autenticación" })).toHaveCount(0);

  await page.getByLabel("Contraseña actual para reemplazar el factor").fill("synthetic current phrase");
  await page.getByLabel("Código temporal actual").fill("123456");
  await page.getByRole("button", { name: "Preparar factor nuevo" }).click();
  await expect(page.getByRole("heading", { name: "Configura la nueva aplicación" })).toBeVisible();
  await expect(page.getByLabel("Clave manual de autenticación")).toContainText("ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567");
  await expect(page.getByText("Sesión activa: personal")).toBeVisible();
  expect(requests).toEqual([
    { body: { currentPassword: "bad password", totpCode: "123456" }, csrf: csrfToken },
    { body: { currentPassword: "synthetic current phrase", totpCode: "123456" }, csrf: csrfToken },
  ]);
  expect(await page.evaluate(() => ({
    local: localStorage.length,
    session: sessionStorage.length,
    noOverflow: document.documentElement.scrollWidth <= innerWidth,
  }))).toEqual({ local: 0, session: 0, noOverflow: true });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});


test("T067 accepts a recovery-code proof for preparing a new factor without closing the session", async ({ page }) => {
  const csrfToken = "synthetic-csrf-token";
  let preparationBody: unknown;
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 7, role: "staff", csrfToken }),
    });
  });
  await page.route("**/api/admin/totp-replacement/prepare", async (route) => {
    preparationBody = route.request().postDataJSON();
    expect(route.request().headers()["x-csrf-token"]).toBe(csrfToken);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ provisioningUri: "otpauth://totp/BeautyHub:synthetic", manualKey: "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" }),
    });
  });

  await page.goto("/admin/");
  await page.getByLabel("Contraseña actual para reemplazar el factor").fill("synthetic current phrase");
  await page.getByLabel("Código de recuperación", { exact: true }).check();
  await page.getByLabel("Código de recuperación actual").fill("ABCD-EFGH-JKLM-NPQR");
  await page.getByRole("button", { name: "Preparar factor nuevo" }).click();

  await expect(page.getByRole("heading", { name: "Configura la nueva aplicación" })).toBeVisible();
  await expect(page.getByText("Sesión activa: personal")).toBeVisible();
  expect(preparationBody).toEqual({
    currentPassword: "synthetic current phrase",
    recoveryCode: "ABCD-EFGH-JKLM-NPQR",
  });
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("T068 rejects a bad new-factor code without ending the current session or exposing recovery codes", async ({ page }) => {
  const csrfToken = "synthetic-csrf-token";
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 7, role: "staff", csrfToken }),
    });
  });
  await page.route("**/api/admin/totp-replacement/prepare", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ provisioningUri: "otpauth://totp/BeautyHub:synthetic", manualKey: "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" }),
    });
  });
  await page.route("**/api/admin/totp-replacement/confirm", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe(csrfToken);
    expect(route.request().postDataJSON()).toEqual({ totpCode: "000000" });
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({ detail: "No fue posible comprobar las credenciales." }),
    });
  });

  await page.goto("/admin/");
  await page.getByLabel("Contraseña actual para reemplazar el factor").fill("synthetic current phrase");
  await page.getByLabel("Código temporal actual").fill("123456");
  await page.getByRole("button", { name: "Preparar factor nuevo" }).click();
  await expect(page.getByRole("heading", { name: "Configura la nueva aplicación" })).toBeVisible();
  await page.getByLabel("Código de la nueva aplicación").fill("000000");
  await page.getByRole("button", { name: "Confirmar y reemplazar factor" }).click();
  await expect(page.getByRole("alert")).toHaveText("No fue posible comprobar el código. La configuración pendiente se descartó; inicia una nueva preparación.");
  await expect(page.getByRole("img", { name: "Código QR para configurar la nueva aplicación de autenticación" })).toHaveCount(0);
  await expect(page.getByText("Sesión activa: personal")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Guarda tus nuevos códigos de recuperación" })).toHaveCount(0);
});

test("T068 shows the new one-time recovery batch after successful confirmation and closes the session", async ({ page }) => {
  const csrfToken = "synthetic-csrf-token";
  const recoveryCodes = Array.from({ length: 10 }, (_, index) => {
    const alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";
    return `ABCD-EFGH-JKLM-NP${alphabet[index]}${alphabet[index + 1]}`;
  });
  await page.route("**/api/admin/sessions/current", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ accountId: 7, role: "staff", csrfToken }) });
      return;
    }
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/admin/totp-replacement/prepare", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ provisioningUri: "otpauth://totp/BeautyHub:synthetic", manualKey: "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" }),
    });
  });
  await page.route("**/api/admin/totp-replacement/confirm", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe(csrfToken);
    expect(route.request().postDataJSON()).toEqual({ totpCode: "654321" });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "cache-control": "no-store", "referrer-policy": "no-referrer" },
      body: JSON.stringify({ recoveryCodes }),
    });
  });

  await page.goto("/admin/");
  await page.getByLabel("Contraseña actual para reemplazar el factor").fill("synthetic current phrase");
  await page.getByLabel("Código temporal actual").fill("123456");
  await page.getByRole("button", { name: "Preparar factor nuevo" }).click();
  await page.getByLabel("Código de la nueva aplicación").fill("654321");
  await page.getByRole("button", { name: "Confirmar y reemplazar factor" }).click();
  await expect(page.getByRole("heading", { name: "Guarda tus nuevos códigos de recuperación" })).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveCount(10);
  await expect(page.getByText("Sesión activa: personal")).toHaveCount(0);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Ya guardé mis códigos" }).click();
  await expect(page.getByRole("heading", { name: "Iniciar sesión" })).toBeVisible();
  await expect(page.getByText(recoveryCodes[0])).toHaveCount(0);
});
