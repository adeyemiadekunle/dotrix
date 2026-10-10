import { expect, test } from "@playwright/test";

import { NOT_WIRED, signUp, signUpWithProject } from "./helpers";

test.fixme(true, NOT_WIRED);

test("an organisation: invite link, revoke, and the audit log records both", async ({ page }) => {
  await signUp(page);
  const settingsNav = page.getByRole("navigation", { name: "Settings" });
  // A personal workspace invites nobody.
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await settingsNav.getByRole("link", { name: "Invites" }).click();
  await expect(page.getByText("Personal workspaces don't invite: this one is just for you.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create link" })).toHaveCount(0);

  await page
    .getByRole("button", { name: /Personal/ })
    .first()
    .click();
  await page.getByRole("menuitem", { name: /Create organisation/ }).click();
  await page.getByRole("dialog").getByLabel("Name").fill("E2E Ltd");
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(page).toHaveURL(/\/w\/e2e-ltd-/);

  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await settingsNav.getByRole("link", { name: "Members", exact: true }).click();
  await expect(page.getByText("1 person in E2E Ltd.")).toBeVisible();
  await settingsNav.getByRole("link", { name: "Invites" }).click();

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
  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Knowledge", exact: true }).click();
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

test("the project graph: a document names an issue, and each shows the other as related", async ({ page }) => {
  const { key } = await signUpWithProject(page, "Kugraph", "KUG");
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Ship sign-in");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  await page.keyboard.press("Escape");

  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Knowledge", exact: true }).click();
  await page.getByRole("button", { name: "vision.md" }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Edit vision.md").fill(`# Vision\n\nIt starts with ${key}-1.\n`);
  await page.getByRole("button", { name: "Save" }).click();
  const related = page.getByRole("region", { name: "Related" });
  await expect(related.getByText("Mentions")).toBeVisible();
  await related.getByRole("link", { name: `${key}-1` }).click();
  await expect(page).toHaveURL(new RegExp(`/board\\?issue=${key}-1`));
  const drawerRelated = page.getByRole("dialog").getByRole("region", { name: "Related" });
  await expect(drawerRelated.getByText("Mentioned in")).toBeVisible();
  await expect(drawerRelated.getByRole("link", { name: "vision.md" })).toBeVisible();

  // Drawn: the issue in the middle, the document beside it; click it to centre on it.
  await drawerRelated.getByRole("link", { name: "Graph" }).click();
  await expect(page).toHaveURL(new RegExp(`/knowledge\\?graph=${key}-1`));
  await expect(page.getByRole("img", { name: `The project graph around ${key}-1` })).toBeVisible();
  await page.getByRole("button", { name: /^vision\.md: / }).click();
  await expect(page.getByRole("img", { name: "The project graph around vision.md" })).toBeVisible();
});

test("turn the personal workspace into an organisation, then restrict a project", async ({ page }) => {
  await signUpWithProject(page, "Kuturn", "KUT");
  const projectSettings = page.url().replace(/\/board.*$/, "/settings");
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: "Invites" }).click();
  await page.getByLabel("Organisation name").fill("Kunemi Ltd");
  await page.getByRole("button", { name: "Turn into an organisation" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Turn into an organisation" }).click();
  // It can invite now, and keeps its project; a new personal workspace is in the switcher.
  await expect(page.getByRole("button", { name: "Create link" })).toBeVisible();
  await page
    .getByRole("button", { name: /Kunemi Ltd/ })
    .first()
    .click();
  await expect(page.getByRole("menuitem", { name: /Personal/ })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto(projectSettings);
  await page.getByRole("combobox", { name: "Who can see this project" }).click();
  await page.getByRole("option", { name: "Only people added" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Restrict" }).click();
  await expect(page.getByRole("combobox", { name: "Who can see this project" })).toHaveText(/Only people added/);
  await expect(page.getByRole("list", { name: "People who can see it" }).getByText("sees every project")).toBeVisible();
});

test("move a project from the personal workspace into an organisation", async ({ page }) => {
  const { key } = await signUpWithProject(page, "Kumove", "KUM");
  const personalUrl = page.url().replace(/\/board.*$/, "/settings");
  await page
    .getByRole("button", { name: /Personal/ })
    .first()
    .click();
  await page.getByRole("menuitem", { name: /Create organisation/ }).click();
  await page.getByLabel("Name").fill("Kunemi Ltd");
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(page).toHaveURL(/\/w\/kunemi-ltd-/);

  await page.goto(personalUrl);
  await page.getByRole("combobox", { name: "Workspace to move to" }).click();
  await page.getByRole("option", { name: /Kunemi Ltd/ }).click();
  await page.getByRole("button", { name: "Move", exact: true }).click();
  await page.getByRole("button", { name: "Move project" }).click();
  await expect(page).toHaveURL(new RegExp(`/w/kunemi-ltd-[a-z0-9]+/p/${key}/settings`));
  await expect(page.getByRole("heading", { name: /General/ })).toBeVisible();
});
