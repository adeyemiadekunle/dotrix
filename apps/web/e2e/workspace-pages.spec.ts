import { expect, test } from "@playwright/test";

import { signUpWithProject } from "./helpers";

test("the workspace's pages: overview, tasks, activity, projects, and search", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Retry failed uploads");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  await page.keyboard.press("Escape");

  const sidebar = page.locator("[data-sidebar=sidebar]").first();

  // The workspace's pages start with Overview; a project's views fold away.
  const workspaceLinks = sidebar.locator("[data-sidebar=group]").filter({ hasText: "Workspace" }).getByRole("link");
  await expect(workspaceLinks.first()).toHaveText("Overview");
  await expect(sidebar.getByRole("list", { name: "Kumove views" })).toBeVisible();
  await sidebar.getByRole("button", { name: "Hide Kumove views" }).click();
  await expect(sidebar.getByRole("list", { name: "Kumove views" })).toHaveCount(0);
  await sidebar.getByRole("button", { name: "Show Kumove views" }).click();
  await expect(sidebar.getByRole("list", { name: "Kumove views" })).toBeVisible();

  // Overview: the project in the portfolio with its open issue.
  await sidebar.getByRole("link", { name: "Overview", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Kumove" })).toBeVisible();

  // Tasks: every issue, with its project.
  await sidebar.getByRole("link", { name: "Tasks", exact: true }).click();
  await expect(page.getByRole("link", { name: new RegExp(`${key}-1.*Retry failed uploads`) })).toBeVisible();

  // Activity across projects names the project.
  await sidebar.getByRole("link", { name: "Activity", exact: true }).first().click();
  await expect(page.getByText(/created/).first()).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Kumove" }).first()).toBeVisible();

  // Projects: progress on the card.
  await sidebar.getByRole("link", { name: "Projects", exact: true }).click();
  await expect(page.getByText("0/1 done")).toBeVisible();

  // ⌘K / Ctrl+K: find the issue and open it.
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("combobox", { name: "Search" }).fill("retry failed");
  await expect(page.getByRole("option", { name: /Retry failed uploads/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/p/${key}/board\\?issue=${key}-1`));
  await page.keyboard.press("Escape");

  // People: open their issues on Tasks.
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("combobox", { name: "Search" }).fill("ada");
  await page.getByRole("option", { name: /Ada Tester/ }).click();
  await expect(page).toHaveURL(/\/tasks\?assignee=/);

  // Agents: Chat opens with that agent picked; or ask the agents what you typed.
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("combobox", { name: "Search" }).fill("research");
  await page.getByRole("option", { name: /Research agent/ }).click();
  await expect(page).toHaveURL(/\/chat\?/);
  await expect(page.getByLabel("Message Research agent")).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByRole("combobox", { name: "Search" }).fill("what is blocked");
  await page.getByRole("option", { name: /Ask the agents in Chat/ }).click();
  await expect(page.getByLabel("Message the agents")).toHaveValue("what is blocked");

  // The profile menu: keyboard shortcuts and connecting the CLI.
  const userMenu = sidebar.getByRole("button", { name: /Ada Tester/ });
  await userMenu.click();
  await page.getByRole("menuitem", { name: "Keyboard shortcuts" }).click();
  await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toContainText("Show or hide the sidebar");
  await page.keyboard.press("Escape");
  await userMenu.click();
  await page.getByRole("menuitem", { name: "Connect the CLI" }).click();
  await expect(page.getByRole("dialog", { name: "Connect the CLI" })).toContainText("pmagent login");
});
