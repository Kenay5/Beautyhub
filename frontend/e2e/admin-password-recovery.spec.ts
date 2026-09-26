import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const csrfToken = "synthetic-csrf-token";
const recoveryToken = "A".repeat(43);
const genericRecoveryMessage = "Si existe una cuenta activa con ese correo, recibirás instrucciones para recuperar tu contraseña.";

test("T077 gives the same recovery-request response for existing and absent synthetic accounts", async ({ page }) => {
  const requestedEmails: string[] = [];
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
  });
  await page.route("**/api/admin/password-recovery", async (route) => {
    requestedEmails.push((route.request().postDataJSON() as { email: string }).email);
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ message: genericRecoveryMessage }),
    });
  });

  await page.goto("/admin/");
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  await page.getByRole("button", { name: "¿Olvidaste tu contraseña?" }).click();
  await expect(page.getByRole("heading", { name: "Recuperar contraseña" })).toBeVisible();
  const email = page.getByLabel("Correo", { exact: true });
  await email.fill("absent.synthetic@example.test");
  await page.getByRole("button", { name: "Enviar instrucciones" }).click();
  await expect(page.getByRole("status")).toHaveText(genericRecoveryMessage);

  await email.fill("active.synthetic@example.test");
  await page.getByRole("button", { name: "Enviar instrucciones" }).click();
  await expect(page.getByRole("status")).toHaveText(genericRecoveryMessage);
  expect(requestedEmails).toEqual([
    "absent.synthetic@example.test",
    "active.synthetic@example.test",
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("T077 changes the signed-in person's password after failures without retaining credentials", async ({ page }) => {
  const requests: unknown[] = [];
  const outcomes = [400, 422, 204];
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ accountId: 7, role: "staff", csrfToken }),
    });
  });
  await page.route("**/api/admin/password", async (route) => {
    requests.push({ body: route.request().postDataJSON(), csrf: route.request().headers()["x-csrf-token"] });
    const status = outcomes.shift();
    if (status === 204) await route.fulfill({ status });
    else await route.fulfill({ status: status ?? 500, contentType: "application/json", body: JSON.stringify({ detail: "synthetic failure" }) });
  });

  await page.goto("/admin/");
  const passwordForm = page.getByRole("region", { name: "Cambiar contraseña" });
  const currentPassword = passwordForm.getByLabel("Contraseña actual", { exact: true });
  const totp = passwordForm.getByLabel("Código de 6 dígitos");
  const newPassword = passwordForm.getByLabel("Nueva contraseña");
  await expect(currentPassword).toHaveAttribute("autocomplete", "current-password");
  await expect(newPassword).toHaveAttribute("autocomplete", "new-password");
  await expect(totp).toHaveAttribute("autocomplete", "one-time-code");

  for (const message of [
    "No fue posible comprobar las credenciales.",
    "La nueva contraseña no es válida. Usa entre 12 y 128 caracteres y evita contraseñas comunes.",
  ]) {
    await currentPassword.fill("synthetic current phrase");
    await totp.fill("123456");
    await newPassword.fill("synthetic replacement phrase");
    await passwordForm.getByRole("button", { name: "Cambiar contraseña" }).click();
    await expect(passwordForm.getByRole("alert")).toHaveText(message);
    await expect(currentPassword).toBeEmpty();
    await expect(totp).toBeEmpty();
    await expect(newPassword).toBeEmpty();
    await expect(page.getByText("Sesión activa: personal")).toBeVisible();
  }

  await currentPassword.fill("synthetic current phrase");
  await totp.fill("123456");
  await newPassword.fill("synthetic replacement phrase");
  await passwordForm.getByRole("button", { name: "Cambiar contraseña" }).click();
  await expect(page.getByText("Tu contraseña fue actualizada. Inicia sesión nuevamente.")).toBeVisible();
  expect(requests).toEqual(Array.from({ length: 3 }, () => ({
    body: { currentPassword: "synthetic current phrase", totpCode: "123456", newPassword: "synthetic replacement phrase" },
    csrf: csrfToken,
  })));
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("T077 completes a recovery link without creating a session and keeps second factor mandatory", async ({ page }) => {
  const completionRequests: unknown[] = [];
  await page.route("**/api/admin/password-recovery/complete", async (route) => {
    const body = route.request().postDataJSON() as { token: string; newPassword: string };
    completionRequests.push(body);
    if (body.newPassword === "synthetic blocked phrase") {
      await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "synthetic internal policy detail" }) });
      return;
    }
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
  });

  await page.goto(`/admin/password-recovery#token=${recoveryToken}`);
  await expect(page.getByRole("heading", { name: "Elige una contraseña nueva" })).toBeVisible();
  await expect(page.getByText("Tu verificación en dos pasos seguirá siendo obligatoria.")).toBeVisible();
  await page.getByLabel("Nueva contraseña").fill("synthetic blocked phrase");
  await page.getByLabel("Confirmar contraseña").fill("synthetic blocked phrase");
  await page.getByRole("button", { name: "Restablecer contraseña" }).click();
  await expect(page.getByRole("alert")).toHaveText("La contraseña no cumple los requisitos de seguridad. El enlace sigue disponible; intenta con otra.");
  await expect(page.getByText("synthetic internal policy detail")).toHaveCount(0);

  await page.getByLabel("Nueva contraseña").fill("synthetic replacement phrase");
  await page.getByLabel("Confirmar contraseña").fill("synthetic replacement phrase");
  await page.getByRole("button", { name: "Restablecer contraseña" }).click();
  await expect(page.getByRole("heading", { name: "Contraseña restablecida" })).toBeVisible();
  await expect(page.getByText(/No se ha iniciado ninguna sesión/)).toBeVisible();
  expect(completionRequests).toEqual([
    { token: recoveryToken, newPassword: "synthetic blocked phrase" },
    { token: recoveryToken, newPassword: "synthetic replacement phrase" },
  ]);
  expect(await page.context().cookies()).toEqual([]);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("link", { name: "Ir al inicio de sesión" }).click();
  await expect(page.getByRole("heading", { name: "Acceso administrativo" })).toBeVisible();
  await expect(page.getByLabel("Código de 6 dígitos")).toBeVisible();
});

test("T077 lets an owner order a forced reset, then blocks factor replacement until old-factor login", async ({ page }) => {
  let role: "owner" | "staff" | null = "owner";
  const loginBodies: unknown[] = [];
  const forcedResetBodies: unknown[] = [];
  await page.route("**/api/admin/sessions/current", async (route) => {
    if (role === null) {
      await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
      return;
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ accountId: 7, role, csrfToken }) });
  });
  await page.route("**/api/admin/staff-password-reset", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe(csrfToken);
    forcedResetBodies.push(route.request().postData());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ deliveryStatus: "accepted" }) });
  });
  await page.route("**/api/admin/password-recovery/complete", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ token: recoveryToken, newPassword: "synthetic forced replacement phrase" });
    role = null;
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/admin/sessions", async (route) => {
    const body = route.request().postDataJSON() as { email: string; password: string; totpCode: string };
    loginBodies.push(body);
    if (body.password === "synthetic old password") {
      await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
      return;
    }
    role = "staff";
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ role: "staff", csrfToken }) });
  });
  await page.route("**/api/admin/totp-replacement/prepare", async (route) => {
    expect(route.request().headers()["x-csrf-token"]).toBe(csrfToken);
    await route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "synthetic restriction detail" }) });
  });
  page.on("dialog", (dialog) => dialog.accept());

  await page.goto("/admin/");
  await expect(page.getByText("Sesión activa: propietario")).toBeVisible();
  await page.getByRole("button", { name: "Enviar enlace para crear una contraseña nueva" }).click();
  await expect(page.getByRole("status")).toHaveText("Se envió al personal un enlace para crear una contraseña nueva.");
  await expect(page.getByLabel("Contraseña nueva del personal")).toHaveCount(0);
  expect(forcedResetBodies).toEqual([null]);

  await page.goto(`/admin/password-recovery#token=${recoveryToken}`);
  await page.getByLabel("Nueva contraseña").fill("synthetic forced replacement phrase");
  await page.getByLabel("Confirmar contraseña").fill("synthetic forced replacement phrase");
  await page.getByRole("button", { name: "Restablecer contraseña" }).click();
  await expect(page.getByRole("heading", { name: "Contraseña restablecida" })).toBeVisible();

  await page.getByRole("link", { name: "Ir al inicio de sesión" }).click();
  await page.getByLabel("Correo electrónico").fill("synthetic.staff@example.test");
  await page.getByLabel("Contraseña").fill("synthetic old password");
  await page.getByLabel("Código de 6 dígitos").fill("123456");
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Las credenciales no son válidas. Revisa los datos e inténtalo de nuevo.")).toBeVisible();
  await page.getByLabel("Correo electrónico").fill("synthetic.staff@example.test");
  await page.getByLabel("Contraseña").fill("synthetic forced replacement phrase");
  await page.getByLabel("Código de 6 dígitos").fill("123456");
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Sesión activa: personal")).toBeVisible();

  const oldPassword = page.getByLabel("Contraseña actual para reemplazar el factor");
  await oldPassword.fill("synthetic forced replacement phrase");
  await page.getByLabel("Código temporal actual").fill("123456");
  await page.getByRole("button", { name: "Preparar factor nuevo" }).click();
  await expect(page.getByRole("alert")).toHaveText("No tienes permiso para realizar esta operación.");
  await expect(page.getByRole("img", { name: "Código QR para configurar la nueva aplicación de autenticación" })).toHaveCount(0);
  await expect(page.getByText("synthetic restriction detail")).toHaveCount(0);
  expect(loginBodies).toEqual([
    { email: "synthetic.staff@example.test", password: "synthetic old password", totpCode: "123456" },
    { email: "synthetic.staff@example.test", password: "synthetic forced replacement phrase", totpCode: "123456" },
  ]);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});


test("T078 keeps the second factor mandatory after password recovery when all old factors are unavailable", async ({ page }) => {
  let sessionAttempts = 0;
  const recoveryRequests: unknown[] = [];
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
  });
  await page.route("**/api/admin/password-recovery", async (route) => {
    recoveryRequests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ message: genericRecoveryMessage }),
    });
  });
  await page.route("**/api/admin/password-recovery/complete", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ token: recoveryToken, newPassword: "synthetic recovered phrase" });
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/admin/sessions", async (route) => {
    sessionAttempts += 1;
    await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
  });

  await page.goto("/admin/");
  await page.getByRole("button", { name: "¿Olvidaste tu contraseña?" }).click();
  await page.getByLabel("Correo", { exact: true }).fill("synthetic.staff@example.test");
  await page.getByRole("button", { name: "Enviar instrucciones" }).click();
  await expect(page.getByRole("status")).toHaveText(genericRecoveryMessage);
  expect(recoveryRequests).toEqual([{ email: "synthetic.staff@example.test" }]);

  await page.goto(`/admin/password-recovery#token=${recoveryToken}`);
  await page.getByLabel("Nueva contraseña").fill("synthetic recovered phrase");
  await page.getByLabel("Confirmar contraseña").fill("synthetic recovered phrase");
  await page.getByRole("button", { name: "Restablecer contraseña" }).click();
  await expect(page.getByRole("heading", { name: "Contraseña restablecida" })).toBeVisible();
  await expect(page.getByText(/No se ha iniciado ninguna sesión/)).toBeVisible();

  await page.getByRole("link", { name: "Ir al inicio de sesión" }).click();
  await page.getByLabel("Correo electrónico").fill("synthetic.staff@example.test");
  await page.getByLabel("Contraseña").fill("synthetic recovered phrase");
  const totp = page.getByLabel("Código de 6 dígitos");
  await expect(totp).toHaveAttribute("required", "");
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(totp).toBeFocused();
  expect(sessionAttempts).toBe(0);
  await expect(page.getByRole("link", { name: /reemplazar.*factor/i })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
