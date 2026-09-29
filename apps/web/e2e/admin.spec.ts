import { expect, test } from "@playwright/test";

import { signUp, signUpWithProject } from "./helpers";

test("a workspace in an organisation: invite link, revoke, and the audit log records both", async ({ page }) => {
  await signUp(page);
  // A personal workspace invites nobody.
  await page.getByRole("link", { name: "Members and settings" }).click();
  await expect(page.getByText("A personal workspace is just for you: nobody else can join it while it stays personal.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create link" })).toHaveCount(0);

  // A new workspace needs an organisation: with none yet, the dialog offers to create one.
  await page.getByRole("button", { name: /Personal/ }).first().click();
  await page.getByRole("menuitem", { name: "Create workspace" }).click();
  await page.getByRole("button", { name: "Create an organisation" }).click();
  await page.getByRole("dialog").getByLabel("Name").fill("E2E Ltd");
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(page).toHaveURL(/\/o\/e2e-ltd/);

  await page.getByRole("button", { name: /Personal/ }).first().click();
  await page.getByRole("menuitem", { name: "Create workspace" }).click();
  await page.getByRole("dialog").getByLabel("Name").fill("E2E Team");
  await expect(page.getByRole("dialog").getByLabel("Organisation")).toHaveText(/E2E Ltd/);
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

test("an organisation: create it from the workspace menu, then a workspace in it", async ({ page }) => {
  await signUp(page);
  await page.getByRole("button", { name: /Personal/ }).first().click();
  await page.getByRole("menuitem", { name: /Create organisation/ }).click();
  await page.getByLabel("Name").fill("Kunemi Ltd");
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(page).toHaveURL(/\/o\/kunemi-ltd/);
  await expect(page.getByRole("heading", { name: "Workspaces", exact: true })).toBeVisible();
  await expect(page.getByText("No workspaces yet")).toBeVisible();
  // The sidebar lists it once there is one.
  await expect(page.getByRole("link", { name: "Kunemi Ltd" })).toBeVisible();

  await page.getByRole("button", { name: "New workspace" }).click();
  await page.getByLabel("Name").fill("Payments team");
  await page.getByRole("button", { name: "Create workspace" }).click();
  const row = page.getByRole("listitem").filter({ hasText: "Payments team" });
  await expect(row).toBeVisible();
  await expect(row.getByText("you're owner")).toBeVisible();
});

test("move a project from the personal workspace into an organisation's workspace", async ({ page }) => {
  const { key } = await signUpWithProject(page, "Kumove", "KUM");
  const personalUrl = page.url().replace(/\/board.*$/, "/settings");
  await page.getByRole("button", { name: /Personal/ }).first().click();
  await page.getByRole("menuitem", { name: /Create organisation/ }).click();
  await page.getByLabel("Name").fill("Kunemi Ltd");
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(page).toHaveURL(/\/o\/kunemi-ltd/);
  await page.getByRole("button", { name: "New workspace" }).click();
  await page.getByLabel("Name").fill("Payments team");
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Payments team" })).toBeVisible();

  await page.goto(personalUrl);
  await page.getByRole("combobox", { name: "Workspace to move to" }).click();
  await page.getByRole("option", { name: /Payments team/ }).click();
  await page.getByRole("button", { name: "Move", exact: true }).click();
  await page.getByRole("button", { name: "Move project" }).click();
  await expect(page).toHaveURL(new RegExp(`/w/payments-team-[a-z0-9]+/p/${key}/settings`));
  await expect(page.getByRole("heading", { name: /General/ })).toBeVisible();
});
