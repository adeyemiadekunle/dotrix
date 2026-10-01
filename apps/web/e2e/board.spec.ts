import { expect, test } from "@playwright/test";

import { signUpWithProject } from "./helpers";

test("create an issue, move it, and comment on it", async ({ page }) => {
  const { key } = await signUpWithProject(page);

  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Write the onboarding docs");
  await page.getByRole("button", { name: "Create issue" }).click();

  // The new issue opens in the drawer.
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByLabel("Title")).toHaveValue("Write the onboarding docs");

  await drawer.getByLabel("Status").click();
  await page.getByRole("option", { name: "In progress" }).click();
  await expect(drawer.getByText("changed status from To do to In progress")).toBeVisible();

  await drawer.getByPlaceholder("Add a comment (Markdown supported)").fill("Starting with the **CLI** guide.");
  await drawer.getByRole("button", { name: "Comment" }).click();
  await expect(drawer.getByText("Starting with the")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  // On the board, in the In progress column.
  const inProgress = page.locator("section").filter({ has: page.getByText("In progress", { exact: true }) });
  await expect(inProgress.getByText("Write the onboarding docs")).toBeVisible();

  // Search filters the board and lives in the URL.
  await page.getByLabel("Search issues").fill("nothing matches this");
  await expect(page).toHaveURL(/q=nothing/);
  await expect(page.getByText("Write the onboarding docs")).toHaveCount(0);
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page.getByText("Write the onboarding docs")).toBeVisible();
});

test("a new issue like an existing one points to it", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Add dark mode to the dispatch screen");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Add a dark mode toggle");
  await expect(page.getByText("Similar issues already exist. Is it one of these?")).toBeVisible();
  // Opening the match instead of creating a duplicate.
  await page.getByRole("button", { name: `${key}-1 Add dark mode to the dispatch screen` }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
});

test("a column's + starts the issue in that column, and the Filter menu narrows the board", async ({ page }) => {
  const { key } = await signUpWithProject(page);

  await page.getByRole("button", { name: "Add to Blocked" }).click();
  await expect(page.getByText("It starts in Blocked.")).toBeVisible();
  await page.getByLabel("Title").fill("Waiting on the pricing rules");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  await page.keyboard.press("Escape");

  const blocked = page.locator("section").filter({ has: page.getByText("Blocked", { exact: true }) });
  await expect(blocked.getByText("Waiting on the pricing rules")).toBeVisible();

  // A filter from the menu shows as a chip; removing the chip brings the issue back.
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  await page.getByRole("menuitem", { name: "Type" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Bug" }).click();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/type=bug/);
  await expect(page.getByText("Waiting on the pricing rules")).toHaveCount(0);
  await page.getByRole("button", { name: "Remove the type filter" }).click();
  await expect(page.getByText("Waiting on the pricing rules")).toBeVisible();
});

test("project settings save through the unsaved-changes bar", async ({ page }) => {
  await signUpWithProject(page, "Kumove", "KUM");
  await page.getByRole("link", { name: "Project settings" }).click();

  // The bar only appears once something has changed.
  await expect(page.getByText("Unsaved changes")).toHaveCount(0);
  await page.getByLabel("Name").fill("Kumove app");
  await expect(page.getByText("Unsaved changes")).toBeVisible();
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByLabel("Name")).toHaveValue("Kumove");

  await page.getByLabel("Name").fill("Kumove app");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Unsaved changes")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Kumove app" })).toBeVisible();
});

test("the keyboard moves a card to the next column", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Draft the pricing page");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  await page.keyboard.press("Escape");

  // Space picks the card up, the right arrow moves it to In progress, Space drops it.
  const card = page.getByRole("button", { name: /Draft the pricing page/ });
  await card.focus();
  await page.keyboard.press("Space");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Space");

  const inProgress = page.locator("section").filter({ has: page.getByText("In progress", { exact: true }) });
  await expect(inProgress.getByText("Draft the pricing page")).toBeVisible();
  await page.reload();
  await expect(inProgress.getByText("Draft the pricing page")).toBeVisible();
});
