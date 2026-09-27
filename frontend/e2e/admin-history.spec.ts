import { tmpdir } from "node:os";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";


const ownerSession = {
  accountId: 1,
  role: "owner",
  csrfToken: "synthetic-csrf-token",
};
const staffSession = {
  accountId: 8,
  role: "staff",
  csrfToken: "synthetic-csrf-token",
};
const ownerEvents = {
  events: [
    {
      eventId: 31,
      actorAccountId: 7,
      action: "appointment_modified",
      result: "succeeded",
      occurredAt: "2026-09-26T16:00:00Z",
      targetReference: "appointment:21",
    },
  ],
  accountIds: [7, 8],
};


test("T086 owner filters, opens minimal detail, and retains accessible responsive history", async ({ page }, testInfo) => {
  const queries: string[] = [];
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(ownerSession) });
  });
  await page.route("**/api/admin/history**", async (route) => {
    queries.push(new URL(route.request().url()).search);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(ownerEvents) });
  });
  await page.route("**/api/admin/history/31", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(ownerEvents.events[0]),
    });
  });

  await page.goto("/admin/");
  await page.getByRole("button", { name: "Historial administrativo" }).click();
  await expect(page.getByRole("heading", { name: "Historial administrativo" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Eventos administrativos encontrados" })).toBeVisible();
  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow.getByText("Cuenta 7")).toBeVisible();
  await expect(firstRow.getByText("Cita modificada")).toBeVisible();
  await expect(firstRow.getByText("Exitoso")).toBeVisible();
  await expect(firstRow).toContainText("26 sep 2026");
  await expect(firstRow).toContainText("10:00");
  if ((testInfo.project.use.viewport?.width ?? 0) <= 390) {
    await expect(page.getByText("Desliza la tabla horizontalmente para consultar todas las columnas.")).toBeVisible();
  }

  await page.getByLabel("Desde").fill("2026-09-26");
  await page.getByLabel("Hasta").fill("2026-09-26");
  await page.getByLabel("Cuenta").selectOption("7");
  await page.getByLabel("Tipo de acción").selectOption("appointment_modified");
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect.poll(() => queries.length).toBeGreaterThanOrEqual(2);
  expect(queries.at(-1)).toContain("accountId=7");
  expect(queries.at(-1)).toContain("action=appointment_modified");
  expect(queries.at(-1)).toContain("fromDate=2026-09-26");
  expect(queries.at(-1)).toContain("toDate=2026-09-26");

  const detailButton = page.getByRole("button", { name: "Ver evento 31" });
  await detailButton.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Detalle del evento" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("appointment:21")).toBeVisible();
  await expect(dialog.getByText("Cuenta 7")).toBeVisible();
  await expect((await new AxeBuilder({ page }).include(".admin-history-page").analyze()).violations).toEqual([]);
  await expect((await new AxeBuilder({ page }).include(".admin-history-dialog").analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(detailButton).toBeFocused();
  const overflow = await page.evaluate(() => ({
    pageWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    elements: [...document.querySelectorAll("body *")]
      .map((element) => ({
        tag: element.tagName,
        className: typeof element.className === "string" ? element.className : "",
        text: element.textContent?.trim().slice(0, 60) ?? "",
        left: Math.round(element.getBoundingClientRect().left),
        right: Math.round(element.getBoundingClientRect().right),
        scrollWidth: element.scrollWidth,
      }))
      .filter((element) => element.right > window.innerWidth || element.left < 0)
      .slice(0, 12),
  }));
  expect(overflow.pageWidth, JSON.stringify(overflow.elements)).toBeLessThanOrEqual(overflow.viewportWidth);

  const width = testInfo.project.use.viewport?.width;
  if (testInfo.project.name === "chromium-320" || testInfo.project.name === "chromium-1280") {
    await page.locator(".admin-history-table-scroll").evaluate((element) => {
      element.scrollLeft = 0;
    });
    await page.screenshot({
      path: join(tmpdir(), `beautyhub-admin-history-${width}.png`),
      fullPage: true,
    });
  }
});


test("T086 staff has no history navigation and direct listing is forbidden", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/admin/sessions/current", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(staffSession) });
  });
  await page.route("**/api/admin/history**", async (route) => {
    attempts += 1;
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({ detail: "No tienes permiso para consultar el historial administrativo." }),
    });
  });

  await page.goto("/admin/");
  await expect(page.getByText("Tu sesión de personal está activa.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Historial administrativo" })).toHaveCount(0);
  const status = await page.evaluate(async () => {
    const response = await fetch("/api/admin/history/31", {
      credentials: "same-origin",
      headers: { "x-admin-role": "owner", "x-admin-account-id": "1" },
    });
    return response.status;
  });
  expect(status).toBe(403);
  expect(attempts).toBe(1);
  await expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
