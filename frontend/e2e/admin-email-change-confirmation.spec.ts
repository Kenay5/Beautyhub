import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const token = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8";

test("T075 confirms an email change without exposing the link or losing mobile access", async ({ page }) => {
  const requests: Array<{ body: unknown; referer: string | undefined }> = [];
  await page.route("**/api/admin/account/email-change/complete", async (route) => {
    requests.push({ body: route.request().postDataJSON(), referer: route.request().headers().referer });
    await route.fulfill({ status: 204, body: "" });
  });

  await page.goto(`/admin/email-change#token=${token}`);
  await expect(page).toHaveURL(/\/admin\/email-change$/);
  await expect(page.getByRole("heading", { name: "Confirmar correo nuevo" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirmar cambio de correo" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("button", { name: "Confirmar cambio de correo" }).click();
  await expect(page.getByRole("heading", { name: "Correo cambiado" })).toBeVisible();
  expect(requests).toEqual([{ body: { token }, referer: undefined }]);
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  expect(await page.context().cookies()).toEqual([]);

  await page.reload();
  await expect(page.getByRole("heading", { name: "No fue posible confirmar el cambio" })).toBeVisible();
});
