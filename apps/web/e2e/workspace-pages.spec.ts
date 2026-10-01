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
});
