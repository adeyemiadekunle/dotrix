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
  await page.locator("#main-content").getByRole("button", { name: "Approve" }).click();
  await page.goto("/w/dotrix/chat?tab=coding&session=cs2");
  await expect(page.getByText("Working", { exact: true }).first()).toBeVisible();
});

test("the command palette finds an agent and opens Chat with it", async ({ page }) => {
  await page.goto("/w/dotrix");
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox").fill("research");
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

test("Home's ask box starts a conversation with Nova", async ({ page }) => {
  await page.goto("/w/dotrix");
  await page.getByRole("textbox", { name: "Ask Nova" }).fill("Summarize the project status");
  await page.getByRole("textbox", { name: "Ask Nova" }).press("Enter");
  await expect(page).toHaveURL(/\/chat\?thread=/);
  await expect(page.getByText(/open issues, \d+ in progress/)).toBeVisible();
  await expect(page.locator(".chat-msg .role", { hasText: "Lead" }).first()).toBeVisible();
});

test("always allow from a waiting change: it's approved, and the agent may do it unasked from now on", async ({ page }) => {
  await page.goto("/w/dotrix/chat?thread=th1");
  const doc = page.locator(".change", { hasText: "requirements/navigation.md" });
  await doc.getByRole("button", { name: "Always allow" }).click();
  await expect(page.getByText("Nova may now write documents without asking")).toBeVisible();
  await expect(doc.getByText("Approved", { exact: true })).toBeVisible();

  await page.goto("/w/dotrix/settings/agents");
  await page.locator("#main-content .mini", { hasText: "@auto" }).click();
  await expect(page.getByLabel("write documents without asking")).toHaveValue("allow");
  await expect(page.getByLabel("open issues without asking")).toHaveValue("ask");
});

test("a conversation stopped at its model's limit continues from Chat, or from Notifications", async ({ page }) => {
  await page.goto("/w/dotrix/notifications?n=na5");
  await expect(page.getByText("Stopped at the model's limit.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue when it resets" })).toBeVisible();

  await page.goto("/w/dotrix/chat?thread=th5");
  await expect(page.getByText("Stopped at Anthropic's limit.")).toBeVisible();
  await expect(page.getByText(/It resets in about \d+ minutes?/)).toBeVisible();
  await page.getByRole("button", { name: "Continue now" }).click();
  await expect(page.getByText("Continuing where it stopped")).toBeVisible();
  await expect(page.getByText(/Picking up where I stopped/)).toBeVisible();
  await expect(page.getByText("Stopped at Anthropic's limit.")).toHaveCount(0);
});
