import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://localhost:8100";

/** Wipe learned memory and restore a healthy graph through the real API. */
export async function hardReset(request: APIRequestContext) {
  const r = await request.post(`${API}/api/reset?keep_memory=false`);
  expect(r.ok()).toBeTruthy();
}

/** Open the app and wait until it has loaded the graph over the network. */
export async function openApp(page: Page) {
  await page.goto("/");
  await expect(page.getByText(/falkordb · \d+ services/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("live", { exact: true })).toBeVisible();
  // The header comes from /api/health; the graph is a separate (slower) request on remote hosting.
  await expect(page.getByTestId("graph")).toHaveAttribute("data-ready", "true", { timeout: 60_000 });
}

export async function investigate(page: Page) {
  await page.getByTestId("provider").selectOption("autopilot");
  await page.getByTestId("investigate").click();
  await expect(page.getByTestId("report")).toBeVisible({ timeout: 90_000 });
}

export async function approveAll(page: Page) {
  const approve = page.getByRole("button", { name: "Approve" });
  while (await approve.count()) {
    await approve.first().click();
    await expect(page.getByTestId("toast")).toHaveCount(0);
  }
}

export async function stepCount(page: Page): Promise<number> {
  return page.getByTestId("step").count();
}
