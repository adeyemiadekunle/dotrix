import { expect, test, type Page } from "@playwright/test";

import { createOrganisation, newUser, signUp } from "./helpers";

// Members in a real workspace: an organisation invites people (by email or a link), sees who
// is pending, decides who sees a restricted project, hands over ownership, and removes people.

const slugOf = (page: Page) => new URL(page.url()).pathname.split("/")[2]!;

test("a personal workspace stays private and a separate organisation invites", async ({ page }) => {
  await signUp(page);
  // A personal workspace has no members to manage: its old link opens Home, with no way to invite.
  const personal = slugOf(page);
  await page.goto(`/w/${personal}/members`);
  await expect(page).toHaveURL(new RegExp(`/w/${personal}$`));
  await expect(page.getByRole("button", { name: "Invite member" })).toHaveCount(0);

  await createOrganisation(page);
  await page.goto(`/w/${slugOf(page)}/members`);
  await page.getByRole("button", { name: "Invite member" }).click();
  const email = newUser().email;
  await page.getByLabel("Email addresses", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Send invites" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("1 invitation sent")).toBeVisible();
  const row = page.locator("tr", { hasText: email });
  await expect(row.getByText("Invited")).toBeVisible();

  // Revoking it: gone from the list, and still gone after a reload.
  await row.getByLabel("Member options", { exact: true }).click();
  await page.locator(".mi", { hasText: "Revoke invite" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Revoke invite" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(`Revoked the invite to ${email}`)).toBeVisible();
  await page.reload();
  await expect(page.getByText(email)).toHaveCount(0);
});

test("join by link, see a restricted project once added, then become the owner; removing someone", async ({ page, browser }) => {
  // Two browsers, an organisation, a restricted project, a handover and a removal: close to a minute on its own.
  test.slow();
  await signUp(page, newUser("Ada Owner"));
  await createOrganisation(page);
  const slug = slugOf(page);
  // A project to restrict.
  await page.evaluate(async (s) => {
    const h = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const ws = (await (await fetch("/v1/workspaces", { headers: h })).json()) as { id: string; slug: string }[];
    const w = ws.find((x) => x.slug === s)!;
    await fetch(`/v1/workspaces/${w.id}/projects`, {
      method: "POST",
      headers: h,
      body: JSON.stringify({ key: "SEC", name: "Secret", source: "docs_only", description: "", access: "workspace" }),
    });
  }, slug);

  // The invite link, from the invite dialog.
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto(`/w/${slug}/members`);
  await page.getByRole("button", { name: "Invite member" }).click();
  await page.getByRole("button", { name: "Copy invite link" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(/Invite link copied/)).toBeVisible();
  const link = await page.evaluate(() => navigator.clipboard.readText());
  expect(link).toContain("/invites/accept");

  const other = await browser.newContext();
  const bob = await other.newPage();
  await signUp(bob, newUser("Bob Member"));
  await bob.goto(link);
  await bob.getByRole("button", { name: "Accept and join" }).click();
  await expect(bob).toHaveURL(new RegExp(`/w/${slug}`));

  // A member doesn't see what only owners and admins do: inviting, new projects and teams,
  // the workspace's own settings.
  await bob.goto(`/w/${slug}`);
  await expect(bob.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(bob.getByRole("button", { name: "Invite member" })).toHaveCount(0);
  await expect(bob.getByRole("button", { name: "New project" })).toHaveCount(0);
  await bob.goto(`/w/${slug}/members`);
  await expect(bob.locator("tr", { hasText: "Ada Owner" })).toBeVisible();
  await expect(bob.getByRole("button", { name: "Invite member" })).toHaveCount(0);
  await bob.goto(`/w/${slug}/settings/profile`);
  const nav = bob.getByRole("navigation", { name: "Settings" });
  await expect(nav.getByRole("button", { name: "Profile" })).toBeVisible();
  for (const name of ["Models", "Rules and skills", "Audit log", "Permissions", "Plan"])
    await expect(nav.getByRole("button", { name, exact: true })).toHaveCount(0);

  // Restrict the project and add Bob.
  await page.goto(`/w/${slug}/p/SEC/overview`);
  await page.getByRole("button", { name: "Share" }).click();
  // Added people only count once the project is restricted on the server: wait for that save.
  const restricted = page.waitForResponse((r) => r.request().method() === "PATCH" && /\/projects\/[^/]+$/.test(new URL(r.url()).pathname));
  await page.getByLabel("General access", { exact: true }).selectOption("private");
  expect((await restricted).status()).toBe(200);
  await expect(page.getByText("Owners, admins, and the people added")).toBeVisible();
  await page.getByPlaceholder(/Add people/).fill("Bob");
  await page.getByRole("dialog").locator(".mi", { hasText: "Bob Member" }).click();
  await expect(page.getByRole("dialog").getByText("Added to this project")).toBeVisible();
  await page.keyboard.press("Escape");

  // Hand over the workspace.
  await page.goto(`/w/${slug}/members`);
  const row = page.locator("tr", { hasText: "Bob Member" });
  await row.getByLabel("Member options", { exact: true }).click();
  await page.locator(".mi", { hasText: "Make owner" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Transfer ownership" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Bob Member owns the workspace now")).toBeVisible();
  await expect(row.getByText("Owner", { exact: true })).toBeVisible();

  // Bob, now the owner, removes Ada.
  await bob.goto(`/w/${slug}/members`);
  const ada = bob.locator("tr", { hasText: "Ada Owner" });
  await ada.getByLabel("Member options", { exact: true }).click();
  await bob.locator(".mi", { hasText: "Remove from workspace" }).click();
  await bob.getByRole("dialog").getByRole("button", { name: "Remove member" }).click();
  await expect(bob.getByRole("region", { name: "Notifications" }).getByText("Removed Ada Owner")).toBeVisible();
  await bob.reload();
  await expect(bob.getByText("Ada Owner")).toHaveCount(0);
  await other.close();
});

test("what members can do: an owner grants approving agents' changes", async ({ page }) => {
  await signUp(page);
  await createOrganisation(page);
  await page.goto(`/w/${slugOf(page)}/settings/permissions`);
  await page.getByLabel("Approve agents' changes", { exact: true }).check();
  await page.reload();
  await expect(page.getByLabel("Approve agents' changes", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Edit documents", { exact: true })).not.toBeChecked();
});
