import { expect, test } from "@playwright/test";
import { approveAll, hardReset, investigate, openApp } from "./helpers";

test.beforeEach(async ({ request }) => hardReset(request));

test("two viewers stay in sync over the WebSocket", async ({ browser }) => {
  const a = await (await browser.newContext()).newPage();
  const b = await (await browser.newContext()).newPage();
  await openApp(a);
  await openApp(b);

  // A breaks production; B sees it without reloading.
  await a.getByTestId("scenario-db-pool-exhaustion").click();
  await expect(b.getByTestId("alerts")).toContainText("checkout-api");

  // A investigates; B watches the same steps stream in.
  await investigate(a);
  await expect(b.getByTestId("report")).toContainText("inventory-db-proxy");
  await expect(b.getByTestId("step")).toHaveCount(await a.getByTestId("step").count());

  // B approves; A sees the recovery.
  await approveAll(b);
  await expect(a.getByTestId("incident-resolved")).toBeVisible();
});

test("a late joiner gets the current run replayed", async ({ browser }) => {
  const a = await (await browser.newContext()).newPage();
  await openApp(a);
  await a.getByTestId("scenario-bad-config-push").click();
  await expect(a.getByTestId("alerts")).toContainText("auth-service");
  await investigate(a);

  const late = await (await browser.newContext()).newPage();
  await openApp(late);
  await expect(late.getByTestId("report")).toContainText("feature-flags");
});

test("the UI waits for a sleeping API and loads by itself", async ({ page }) => {
  // Simulate free hosting asleep: every API call fails for a while, then the API "wakes up".
  let asleep = true;
  await page.route(/\/api\//, (route) => (asleep ? route.abort("connectionrefused") : route.continue()));
  await page.routeWebSocket(/\/ws$/, (ws) => {
    if (asleep) ws.close();
    else ws.connectToServer();
  });
  await page.goto("/");
  await expect(page.getByTestId("offline")).toBeVisible();
  await expect(page.getByText(/falkordb · \d+ services/)).toHaveCount(0);

  asleep = false;
  await expect(page.getByTestId("offline")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByText(/falkordb · \d+ services/)).toBeVisible();
  await expect(page.getByTestId("scenario-db-pool-exhaustion")).toBeVisible();
});

test("double-clicking Approve executes the action once", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("scenario-db-pool-exhaustion").click();
  await expect(page.getByTestId("alerts")).toBeVisible();
  await investigate(page);
  const approve = page.getByTestId("approvals").getByRole("button", { name: "Approve" }).first();
  await approve.dblclick();
  await expect(page.getByTestId("done-actions").locator("li")).toHaveCount(1);
  await expect(page.getByTestId("toast")).toHaveCount(0);
  void approveAll;
});
