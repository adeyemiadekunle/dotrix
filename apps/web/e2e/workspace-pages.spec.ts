import { expect, test } from "@playwright/test";

import { NOT_WIRED, signUpWithProject } from "./helpers";

test.fixme(true, NOT_WIRED);

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
  await expect(page.getByRole("dialog", { name: "Connect the CLI" })).toContainText("dotrix login");
});

/** A day as YYYY-MM-DD, `offset` days from today (the browser and this test share a clock). */
function day(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

test("stars, a project's status, My issues as a board and table, and the timeline", async ({ page }) => {
  const { key } = await signUpWithProject(page, "Kumove", "KUM");
  const sidebar = page.locator("[data-sidebar=sidebar]").first();

  // An issue with a start and a due date.
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Ship the timeline");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  await page.getByLabel("Start date").fill(day(-2));
  await page.getByLabel("Start date").press("Enter");
  await page.getByLabel("Due date").fill(day(5));
  await page.getByLabel("Due date").press("Enter");
  await expect(page.getByLabel("Due date")).toHaveValue(day(5));
  await page.keyboard.press("Escape");

  // The project's Timeline: the issue as a bar from start to due.
  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Timeline" }).click();
  await expect(page).toHaveURL(/\/timeline$/);
  const bar = page.getByRole("link", { name: new RegExp(`^${key}-1: `) });
  await expect(bar).toBeVisible();
  // Alt+Shift+Right stretches its end a day (dragging does the same with the mouse).
  await bar.focus();
  await page.keyboard.press("Alt+Shift+ArrowRight");
  await bar.click();
  await expect(page.getByLabel("Due date")).toHaveValue(day(6));
  await page.keyboard.press("Escape");
  // ... and across the workspace, under its project.
  await sidebar.getByRole("link", { name: "Timeline", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Timeline" }).getByText("Ship the timeline")).toBeVisible();

  // My issues (reported by me) as a board, a table, and a timeline.
  await page.goto(page.url().replace(/\/timeline$/, "/my-issues?who=reported"));
  await page.getByRole("button", { name: "Board", exact: true }).click();
  await expect(page.getByRole("region", { name: "To do" }).getByText("Ship the timeline")).toBeVisible();
  await page.getByRole("button", { name: "Table", exact: true }).click();
  await expect(page.getByRole("row", { name: /Ship the timeline/ })).toBeVisible();
  await page.getByRole("button", { name: "Timeline", exact: true }).click();
  await expect(page.getByRole("link", { name: new RegExp(`^${key}-1: `) })).toBeVisible();

  // The project's status and target date, on its card.
  await page.goto(page.url().replace(/\/my-issues.*$/, `/p/${key}/settings`));
  await page.getByLabel("Status").click();
  await page.getByRole("option", { name: "At risk" }).click();
  await page.getByLabel("Target date").fill(day(30));
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  await sidebar.getByRole("link", { name: "Projects", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  const card = page
    .getByRole("main")
    .locator("div")
    .filter({ has: page.getByRole("link", { name: "Kumove", exact: true }) })
    .last();
  await expect(card.getByText("At risk")).toBeVisible();
  await expect(card.getByText(/^Due /)).toBeVisible();

  // Stars: a second project sorts first by key, until Kumove is starred.
  await page.getByRole("link", { name: "New project" }).first().click();
  await page.getByText("Documents only", { exact: true }).click();
  await page.getByLabel("Name").fill("Alpha");
  await page.getByLabel("Key").fill("ALP");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page).toHaveURL(/\/p\/ALP\/overview/);
  const projectLinks = sidebar
    .locator("[data-sidebar=group]")
    .filter({ has: page.locator("[data-sidebar=group-label]", { hasText: /^Projects$/ }) })
    .locator("[data-sidebar=menu-button]");
  await expect(projectLinks.first()).toContainText("Alpha");
  await sidebar.getByRole("link", { name: "Projects", exact: true }).click();
  await page.getByRole("button", { name: "Star Kumove" }).click();
  await expect(page.getByRole("button", { name: "Unstar Kumove" })).toHaveAttribute("aria-pressed", "true");
  await expect(projectLinks.first()).toContainText("Kumove");
  await expect(sidebar.getByLabel("Starred")).toHaveCount(1);
});
