import { expect, test } from "@playwright/test";

import { signUpWithProject } from "./helpers";

test("a project's views: overview, list, table, activity, and My issues", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  const tabs = page.getByRole("navigation", { name: "Project" });

  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Write the onboarding docs");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  await page.keyboard.press("Escape");

  // Overview: progress, what's coming up, and what just happened.
  await tabs.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page.getByText("0 of 1 issues done")).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(`${key}-1.*Write the onboarding docs`) }).first()).toBeVisible();

  // List: ranked, or grouped by status.
  await tabs.getByRole("link", { name: "List", exact: true }).click();
  await expect(page).toHaveURL(/\/list/);
  await expect(page.getByText("Write the onboarding docs")).toBeVisible();
  await page.getByRole("button", { name: "By status" }).click();
  await expect(page).toHaveURL(/group=status/);
  await expect(page.getByRole("button", { name: /To do/ })).toBeVisible();
  // Groups fold, as on My issues; Done starts folded.
  await expect(page.getByRole("button", { name: /Done/ })).toHaveAttribute("aria-expanded", "false");

  // Table: every issue with its columns; a column can be hidden.
  await tabs.getByRole("link", { name: "Table", exact: true }).click();
  await expect(page.getByRole("cell", { name: `${key}-1`, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Columns" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Labels" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("columnheader", { name: "Labels" })).toHaveCount(0);

  // Select issues and change them together.
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Record the demo video");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-2`));
  await page.keyboard.press("Escape");
  await page.getByRole("checkbox", { name: "Select all issues" }).click();
  const bulk = page.getByRole("toolbar", { name: "Selected issues" });
  await expect(bulk.getByText("2 selected")).toBeVisible();
  await bulk.getByRole("button", { name: "Status" }).click();
  await page.getByRole("menuitem", { name: "In progress" }).click();
  await expect(page.getByText("2 issues moved to In progress")).toBeVisible();
  await expect(page.getByRole("cell", { name: "In progress" })).toHaveCount(2);
  await page.getByRole("checkbox", { name: `Select ${key}-2` }).click();
  await bulk.getByRole("button", { name: "Assign" }).click();
  await page.getByRole("menuitem", { name: "Ada Tester" }).click();
  await expect(page.getByText("1 issue assigned to Ada Tester")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Ada Tester" })).toHaveCount(1);

  // Board: cards in each column can be sorted; dragging is for Ranked order.
  await tabs.getByRole("link", { name: "Board", exact: true }).click();
  await page.getByRole("button", { name: "Sort: Ranked" }).click();
  await page.getByRole("menuitemradio", { name: "Newest" }).click();
  await expect(page).toHaveURL(/sort=created/);
  const inProgress = page.locator("section").filter({ has: page.getByText("In progress", { exact: true }) });
  await expect(inProgress.getByText(/Record the demo video|Write the onboarding docs/).first()).toHaveText(
    "Record the demo video",
  );

  // Activity: who did what.
  await tabs.getByRole("link", { name: "Activity", exact: true }).click();
  await expect(page.getByText(/created/).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Write the onboarding docs/ }).first()).toBeVisible();

  // The issue is on My issues too, across projects.
  await page.getByRole("link", { name: "My issues" }).click();
  await page.getByRole("tab", { name: "Reported by me" }).click();
  await expect(page.getByText("Write the onboarding docs")).toBeVisible();
});
