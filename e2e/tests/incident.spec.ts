import { expect, test } from "@playwright/test";
import { API, approveAll, hardReset, investigate, openApp, stepCount } from "./helpers";

test.beforeEach(async ({ request }) => hardReset(request));

test("full incident: break, investigate, approve, recover", async ({ page }) => {
  await openApp(page);
  await expect(page.getByTestId("incident-quiet")).toBeVisible();

  await page.getByTestId("scenario-db-pool-exhaustion").click();
  const alerts = page.getByTestId("alerts");
  await expect(alerts).toContainText("checkout-api");
  await expect(alerts).toContainText("cart-service");
  await expect(alerts).toContainText("orders-service");
  await expect(page.getByTestId("incident-open")).toContainText("3 alerts");

  // The cost of downtime really accumulates while the incident is open.
  const cost = page.getByTestId("cost");
  const first = Number((await cost.innerText()).match(/\$([\d,]+)/)![1].replace(/,/g, ""));
  await page.waitForTimeout(2500);
  const later = Number((await cost.innerText()).match(/\$([\d,]+)/)![1].replace(/,/g, ""));
  expect(later).toBeGreaterThan(first);

  await investigate(page);
  const report = page.getByTestId("report");
  await expect(report).toContainText("inventory-db-proxy");
  await expect(report).toContainText("v4.2.0");
  // Every step shows the Cypher it ran.
  await page.getByTestId("step").filter({ hasText: "find_common_cause" }).getByText("+ cypher").click();
  await expect(page.getByTestId("trail").locator("pre").first()).toContainText("DEPENDS_ON");

  await expect(page.getByTestId("approvals").getByRole("button", { name: "Approve" }).first()).toBeVisible();
  await approveAll(page);
  await expect(page.getByTestId("incident-resolved")).toContainText("MTTR");
  await expect(page.getByTestId("done-actions")).toContainText("rolled back v4.2.0 on inventory-db-proxy");
});

test("the agent proposes, the human can reject", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("scenario-bad-config-push").click();
  await expect(page.getByTestId("alerts")).toContainText("auth-service");
  await investigate(page);
  await expect(page.getByTestId("report")).toContainText("feature-flags");
  const card = page.getByTestId("approvals").locator("div.rounded-md").filter({ hasText: "Page on-call" });
  await card.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByTestId("done-actions")).toContainText("Page on-call feature-flags");
  // Rejecting changes nothing: still an incident.
  await expect(page.getByTestId("incident-open")).toBeVisible();
});

test("red herring: no rollback when the real cause has no deploy", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("scenario-cache-stampede").click();
  await expect(page.getByTestId("alerts")).toContainText("search-service");
  await investigate(page);
  await expect(page.getByTestId("report")).toContainText("redis-cache");
  const approvals = page.getByTestId("approvals");
  await expect(approvals).toContainText("Open circuit breaker");
  await expect(approvals).not.toContainText("Roll back");
});

test("memory: a repeat incident is recognised and takes fewer steps", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("scenario-kafka-rebalance-storm").click();
  await expect(page.getByTestId("alerts")).toContainText("payments-api");
  await investigate(page);
  await expect(page.getByTestId("report")).toContainText("New failure pattern");
  const firstSteps = await stepCount(page);
  await approveAll(page);
  await expect(page.getByTestId("incident-resolved")).toBeVisible();

  await page.getByTestId("scenario-kafka-rebalance-storm").click();
  await expect(page.getByTestId("alerts")).toContainText("payments-api");
  await investigate(page);
  await expect(page.getByTestId("repeat")).toContainText("Seen before");
  expect(await stepCount(page)).toBeLessThan(firstSteps);
  await page.getByTestId("tab-memory").click();
  await expect(page.getByTestId("memory")).toContainText("learned");
});

test("chaos from search: break any service, the agent finds it", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("/");
  await page.keyboard.type("pricing");
  await page.keyboard.press("Enter");
  const card = page.getByTestId("node-card");
  await expect(card).toContainText("pricing-service");
  await card.getByTestId("break-down-true").click();
  await expect(page.getByTestId("incident-open")).toBeVisible();
  await investigate(page);
  await expect(page.getByTestId("report")).toContainText("pricing-service");
  await expect(page.getByTestId("approvals")).toContainText("Roll back");
});

test("reset is not a recovery", async ({ page }) => {
  await openApp(page);
  await page.getByTestId("scenario-db-pool-exhaustion").click();
  await expect(page.getByTestId("incident-open")).toBeVisible();
  await page.getByTestId("reset").click();
  await expect(page.getByTestId("incident-quiet")).toBeVisible();
  await expect(page.getByTestId("incident-resolved")).toHaveCount(0);
});

test("only one investigation at a time", async ({ page, request }) => {
  await openApp(page);
  await page.getByTestId("scenario-db-pool-exhaustion").click();
  await expect(page.getByTestId("alerts")).toBeVisible();
  const a = await request.post(`${API}/api/runs`, { data: { provider: "autopilot" } });
  const b = await request.post(`${API}/api/runs`, { data: { provider: "autopilot" } });
  expect(a.status()).toBe(200);
  expect(b.status()).toBe(409);
  await expect(page.getByTestId("report")).toBeVisible({ timeout: 90_000 });
});
