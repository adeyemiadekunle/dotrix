import { expect, test, type Page } from "@playwright/test";

import { newUser, signUp } from "./helpers";

// Members in a real workspace: an organisation invites people (by email or a link), sees who
// is pending, decides who sees a restricted project, hands over ownership, and removes people.

const slugOf = (page: Page) => new URL(page.url()).pathname.split("/")[2]!;

async function turnIntoOrganisation(page: Page) {
  await page.goto(`/w/${slugOf(page)}/settings/workspace`);
  await page.getByRole("button", { name: "Turn into an organisation" }).click();
  await page.locator(".modal").getByRole("button", { name: "Turn into an organisation" }).click();
  await expect(page.getByText("It's an organisation now")).toBeVisible();
}

test("a personal workspace doesn't invite: it turns into an organisation first", async ({ page }) => {
  await signUp(page);
  await page.goto(`/w/${slugOf(page)}/members`);
  await page.getByRole("button", { name: "Invite member" }).click();
  await expect(page.getByText("A personal workspace is just for you")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send invites" })).toBeDisabled();
  await page.keyboard.press("Escape");

  await turnIntoOrganisation(page);
  await page.goto(`/w/${slugOf(page)}/members`);
  await page.getByRole("button", { name: "Invite member" }).click();
  const email = newUser().email;
  await page.getByLabel("Email addresses").fill(email);
  await page.getByRole("button", { name: "Send invites" }).click();
  await expect(page.getByText("1 invitation sent")).toBeVisible();
  const row = page.locator("tr", { hasText: email });
  await expect(row.getByText("Invited")).toBeVisible();

  // Revoking it: gone from the list, and still gone after a reload.
  await row.getByLabel("Member options").click();
  await page.locator(".mi", { hasText: "Revoke invite" }).click();
  await page.locator(".modal").getByRole("button", { name: "Revoke invite" }).click();
  await expect(page.getByText(`Revoked the invite to ${email}`)).toBeVisible();
  await page.reload();
  await expect(page.getByText(email)).toHaveCount(0);
});

test("join by link, see a restricted project once added, then become the owner; removing someone", async ({ page, browser }) => {
  await signUp(page, newUser("Ada Owner"));
  await turnIntoOrganisation(page);
  const slug = slugOf(page);
  // A project to restrict.
  await page.evaluate(async (s) => {
    const h = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const ws = (await (await fetch("/v1/workspaces", { headers: h })).json()) as { id: string; slug: string }[];
    const w = ws.find((x) => x.slug === s)!;
    await fetch(`/v1/workspaces/${w.id}/projects`, { method: "POST", headers: h, body: JSON.stringify({ key: "SEC", name: "Secret", source: "docs_only", description: "", access: "workspace" }) });
  }, slug);

  // The invite link, from the invite dialog.
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto(`/w/${slug}/members`);
  await page.getByRole("button", { name: "Invite member" }).click();
  await page.getByRole("button", { name: "Copy invite link" }).click();
  await expect(page.getByText(/Invite link copied/)).toBeVisible();
  const link = await page.evaluate(() => navigator.clipboard.readText());
  expect(link).toContain("/invites/accept");

  const other = await browser.newContext();
  const bob = await other.newPage();
  await signUp(bob, newUser("Bob Member"));
  await bob.goto(link);
  await bob.getByRole("button", { name: "Accept and join" }).click();
  await expect(bob).toHaveURL(new RegExp(`/w/${slug}`));

  // Restrict the project and add Bob.
  await page.goto(`/w/${slug}/p/SEC/overview`);
  await page.getByRole("button", { name: "Share" }).click();
  await page.getByLabel("General access").selectOption("private");
  await expect(page.getByText("Owners, admins, and the people added")).toBeVisible();
  await page.getByPlaceholder(/Add people/).fill("Bob");
  await page.locator(".modal .mi", { hasText: "Bob Member" }).click();
  await expect(page.locator(".modal").getByText("Added to this project")).toBeVisible();
  await page.keyboard.press("Escape");

  // Hand over the workspace.
  await page.goto(`/w/${slug}/members`);
  const row = page.locator("tr", { hasText: "Bob Member" });
  await row.getByLabel("Member options").click();
  await page.locator(".mi", { hasText: "Make owner" }).click();
  await page.locator(".modal").getByRole("button", { name: "Transfer ownership" }).click();
  await expect(page.getByText("Bob Member owns the workspace now")).toBeVisible();
  await expect(row.getByText("Owner", { exact: true })).toBeVisible();

  // Bob, now the owner, removes Ada.
  await bob.goto(`/w/${slug}/members`);
  const ada = bob.locator("tr", { hasText: "Ada Owner" });
  await ada.getByLabel("Member options").click();
  await bob.locator(".mi", { hasText: "Remove from workspace" }).click();
  await bob.locator(".modal").getByRole("button", { name: "Remove member" }).click();
  await expect(bob.getByText("Removed Ada Owner")).toBeVisible();
  await bob.reload();
  await expect(bob.getByText("Ada Owner")).toHaveCount(0);
  await other.close();
});

test("what members can do: an owner grants approving agents' changes", async ({ page }) => {
  await signUp(page);
  await turnIntoOrganisation(page);
  await page.goto(`/w/${slugOf(page)}/settings/permissions`);
  await page.getByLabel("Approve agents' changes").check();
  await page.reload();
  await expect(page.getByLabel("Approve agents' changes")).toBeChecked();
  await expect(page.getByLabel("Edit documents")).not.toBeChecked();
});
