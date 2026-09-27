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
