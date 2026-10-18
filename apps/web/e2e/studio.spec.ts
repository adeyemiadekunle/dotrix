import { expect, test } from "@playwright/test";

// The workspace on seeded data (apps/web/src): every screen renders, and dotrix's own flows work
// on it (Chat's conversations and coding sessions come from the API: chat.spec.ts). Data lives in the browser, so each test starts from the seed.

test("every screen renders", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const screens: [string, string][] = [
    ["", "Good"],
    ["inbox", "Inbox"],
    ["my-tasks", "My Tasks"],
    ["favorites", "Favorites"],
    ["notifications", "Inbox"],
    ["overview", "Good"],
    ["chat", "Chat"],
    ["projects", "Projects"],
    ["tasks", "Good"],
    ["calendar", "Good"],
    ["timeline", "Good"],
    ["members", "Members"],
    ["teams", "Teams"],
    ["activity", "Good"],
    ["archive", "Archive"],
    ["settings/agents", "Agents"],
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

test("approve a coding run from the Inbox", async ({ page }) => {
  await page.goto("/w/dotrix/inbox?n=na4");
  await expect(page.getByText("Build the hero component from the wireframes.")).toBeVisible();
  await page.locator("#main-content").getByRole("button", { name: "Approve" }).click();
  await expect(page.locator("#main-content").getByRole("button", { name: "Approve" })).toHaveCount(0);
});

test("the command palette finds an agent and opens Chat with it", async ({ page }) => {
  await page.goto("/w/dotrix");
  await page.keyboard.press("Control+k");
  await page.getByRole("dialog", { name: "Command menu" }).getByRole("combobox").fill("research");
  await page.getByRole("option", { name: /Vega/ }).click();
  await expect(page).toHaveURL(/\/chat\?new=1&agent=research/);
  await expect(page.getByLabel("Agent", { exact: true })).toHaveValue("research");
});

test("the agents panel shows who needs you, and approving from it settles the change", async ({ page }) => {
  await page.goto("/w/dotrix");
  const panel = page.getByRole("complementary", { name: "Agents" });
  await expect(panel.getByText("Nova", { exact: true })).toBeVisible();
  const claude = panel.locator(".ap-row", { hasText: "Claude Code" });
  await expect(claude.getByText("Needs you")).toBeVisible();
  await claude.getByRole("button", { name: "Approve" }).click();
  await expect(claude.getByText("Working")).toBeVisible();

  // Hidden, the same things come as notices in the corner.
  await panel.getByRole("button", { name: "Hide the agents panel" }).click();
  await expect(panel).toBeHidden();
  const notices = page.getByRole("region", { name: "Waiting for you" });
  await expect(notices.getByText("needs your approval").first()).toBeVisible();
  await notices
    .getByRole("button", { name: /Close the notice/ })
    .first()
    .click();
});

test("a conversation stopped at its model's limit offers to continue from the Inbox", async ({ page }) => {
  await page.goto("/w/dotrix/inbox?n=na5");
  await expect(page.getByText("Stopped at the model's limit.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue when it resets" })).toBeVisible();
});

test("a project's files live under Knowledge, and old Files links open them there", async ({ page }) => {
  await page.goto("/w/dotrix/p/WEB/files");
  await expect(page.getByRole("tab", { name: /^Files/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByPlaceholder("Search files")).toBeVisible();
  await page.getByRole("tab", { name: "Documents" }).click();
  await expect(page.getByPlaceholder("Find a document")).toBeVisible();
});
