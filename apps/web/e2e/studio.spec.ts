import { expect, test } from "@playwright/test";

// The workspace on seeded data (apps/web/src): every screen renders, and dotrix's own flows work
// on it. Data lives in the browser, so each test starts from the seed.

test("every screen renders", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const screens: [string, string][] = [
    ["", "Good"],
    ["inbox", "Inbox"],
    ["my-tasks", "My Tasks"],
    ["favorites", "Favorites"],
    ["notifications", "Notifications"],
    ["overview", "Workspace overview"],
    ["chat", "Chat"],
    ["projects", "Projects"],
    ["tasks", "Tasks"],
    ["calendar", "Calendar"],
    ["timeline", "Timeline"],
    ["members", "Members"],
    ["teams", "Teams"],
    ["activity", "Activity"],
    ["archive", "Archive"],
    ["settings/agents", "Agents"],
    ["design-system", "Design system"],
    ["system-states", "System states"],
    ["p/WEB/board", "Website Redesign"],
    ["p/WEB/knowledge", "Website Redesign"],
    ["nowhere", "Page not found"],
  ];
  for (const [path, heading] of screens) {
    await page.goto(`/w/dotrix/${path}`);
    await expect(page.locator("#main-content h1").first(), path).toContainText(heading);
  }
  expect(errors).toEqual([]);
});

test("approve an agent's proposed changes in Chat: the document and the issue appear", async ({ page }) => {
  await page.goto("/w/dotrix/chat?thread=th1");
  await expect(page.getByText("requirements/navigation.md").first()).toBeVisible();
  await page.getByRole("button", { name: "Approve all 2" }).click();
  await expect(page.getByText("Approved", { exact: true })).toHaveCount(2);

  await page.goto("/w/dotrix/p/WEB/knowledge");
  await page.getByRole("button", { name: "navigation.md" }).click();
  await expect(page.getByText("Product, Pricing, Customers, Resources, Company.")).toBeVisible();
});

test("change an agent's plan at its checkpoint, and ask a question", async ({ page }) => {
  await page.goto("/w/dotrix/chat?thread=th2");
  await page.getByRole("button", { name: "Change the plan" }).click();
  await page.getByLabel("Changes to the plan").fill("Skip CRDTs");
  await page.getByRole("button", { name: "Update the plan" }).click();
  await expect(page.getByText("Change the plan: Skip CRDTs")).toBeVisible();
  await expect(page.getByText("Updated the plan with your changes.")).toBeVisible();

  await page.getByLabel("Message").fill("Summarise the project status");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText(/open issues, \d+ in progress/)).toBeVisible();
});

test("approve a coding run from Notifications", async ({ page }) => {
  await page.goto("/w/dotrix/notifications?n=na4");
  await expect(page.getByText("Build the hero component from the wireframes.")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.goto("/w/dotrix/chat?tab=coding&session=cs2");
  await expect(page.getByText("Working", { exact: true }).first()).toBeVisible();
});

test("the command palette finds an agent and opens Chat with it", async ({ page }) => {
  await page.goto("/w/dotrix");
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox").fill("research");
  await page.getByRole("option", { name: /Research agent/ }).click();
  await expect(page).toHaveURL(/\/chat\?new=1&agent=research/);
  await expect(page.getByLabel("Agent")).toHaveValue("research");
});
