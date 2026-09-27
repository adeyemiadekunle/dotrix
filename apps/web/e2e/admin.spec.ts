import { expect, test } from "@playwright/test";

import { signUp, signUpWithProject } from "./helpers";

test("a team workspace: invite link, revoke, and the audit log records both", async ({ page }) => {
  await signUp(page);
  // Create a team workspace from the switcher.
  await page.getByRole("button", { name: /Personal/ }).first().click();
  await page.getByRole("menuitem", { name: "Create workspace" }).click();
  await page.getByLabel("Name").fill("E2E Team");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/w\/e2e-team-/);

  await page.getByRole("link", { name: "Members and settings" }).click();
  await expect(page.getByText("1 person in E2E Team.")).toBeVisible();

  await page.getByRole("button", { name: "Create link" }).click();
  await expect(page.getByText(/\/invites\/accept\?token=/)).toBeVisible();
  const pending = page.getByRole("listitem").filter({ hasText: "Invite link" });
  await expect(pending).toHaveCount(1);
  await pending.getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText("None waiting.")).toBeVisible();

  await page.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByText("created an invite link")).toBeVisible();
  await expect(page.getByText("revoked the invite for")).toBeVisible();
});

test("knowledge: edit a file, see its history, and restore the first version", async ({ page }) => {
  await signUpWithProject(page);
  await page.getByRole("link", { name: "Knowledge", exact: true }).click();
  await page.getByRole("button", { name: "vision.md" }).click();
  await expect(page).toHaveURL(/file=vision\.md/);

  await page.getByRole("button", { name: "Edit" }).click();
  const editor = page.getByLabel("Edit vision.md");
  await editor.fill("# Vision\n\nMove goods across Nigeria in a day.\n");
  await page.getByPlaceholder("What changed? (optional, shown in history)").fill("First draft");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Move goods across Nigeria in a day.")).toBeVisible();

  await page.getByRole("button", { name: "History" }).click();
  await expect(page.getByText("First draft")).toBeVisible();
  await page.getByRole("button", { name: /^v1\b/ }).click();
  await page.getByRole("button", { name: "Restore v1" }).click();
  await expect(page.getByText("Restored version 1")).toBeVisible();
});
