import { expect, test } from "@playwright/test";

import { signUp, signUpWithProject } from "./helpers";

// A 1×1 PNG, as a picked file.
const PIXEL = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

test("your profile in Settings: a photo and what you do, shown to the team in Members", async ({ page }) => {
  await signUpWithProject(page, "Kuprofile", "KUP");
  const settings = page.getByRole("navigation", { name: "Settings" });

  // The user menu opens your profile.
  await page.getByRole("button", { name: /Ada Tester/ }).click();
  await page.getByRole("menuitem", { name: "Profile" }).click();
  await expect(page).toHaveURL(/\/settings\/profile$/);

  await page.getByLabel("Profile photo").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: PIXEL });
  await expect(page.getByRole("button", { name: "Change photo" })).toBeVisible();
  await expect(page.getByRole("main").locator('img[src*="/api/v1/me/avatar"]')).toBeVisible();

  await page.getByLabel("What you do").fill("Product designer");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Profile saved")).toBeVisible();
  await expect(page.getByRole("list", { name: "Sign-in methods" }).getByText("Password", { exact: true })).toBeVisible();

  // Members shows it, with the projects each person sees, and filters by role or text.
  await settings.getByRole("link", { name: "Members", exact: true }).click();
  const row = page.getByRole("listitem").filter({ hasText: "Product designer" });
  await expect(row).toBeVisible();
  await expect(row.getByTestId("projects-they-see")).toHaveText("All projects");
  await page.getByLabel("Search members").fill("nobody-like-this");
  await expect(page.getByText("Nobody matches.")).toBeVisible();
  await page.getByLabel("Search members").fill("designer");
  await expect(row).toBeVisible();

  // Agents and the audit log moved here from the sidebar; old addresses still work.
  await expect(page.locator("[data-sidebar=sidebar]").getByRole("link", { name: "Agents" })).toHaveCount(0);
  await page.goto(page.url().replace(/\/settings\/members$/, "/agents"));
  await expect(page).toHaveURL(/\/settings\/agents$/);
  await expect(page.getByText("@research")).toBeVisible();
  await settings.getByRole("link", { name: "Audit log" }).click();
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
});

test("where you're signed in: see each browser, and sign another one out", async ({ page, browser }) => {
  const user = await signUp(page);
  const other = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const laptop = await other.newPage();
  await laptop.goto("/login");
  await laptop.getByLabel("Email").fill(user.email);
  await laptop.getByLabel("Password").fill(user.password);
  await laptop.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(laptop).toHaveURL(/\/w\//);

  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: "Devices and tokens" }).click();
  const sessions = page.getByRole("list", { name: "Signed-in browsers and apps" });
  await expect(sessions.getByRole("listitem")).toHaveCount(2);
  await expect(sessions.getByRole("listitem").first()).toContainText("This device");
  await expect(sessions.getByRole("listitem").first()).toContainText(/Chrome on/);

  // Sign the other browser out: its next request sends it back to sign in.
  await sessions.getByRole("button", { name: /^Sign out Chrome on \w+$/ }).click();
  await expect(sessions.getByRole("listitem")).toHaveCount(1);
  await laptop.reload();
  await expect(laptop).toHaveURL(/\/login/);
  await other.close();
});

test("change your password in Settings, and choose which notifications you get", async ({ page }) => {
  const user = await signUp(page);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  const settingsNav = page.getByRole("navigation", { name: "Settings" });
  await settingsNav.getByRole("link", { name: "Profile" }).click();

  await page.getByRole("button", { name: "Change password" }).click();
  const dialog = page.getByRole("dialog", { name: "Change your password" });
  await dialog.getByLabel("Current password").fill("not my password");
  await dialog.getByLabel("New password", { exact: true }).fill("a brand new secret");
  await dialog.getByLabel("Confirm new password").fill("a brand new secret");
  await dialog.getByRole("button", { name: "Change password" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("Your current password isn't right");
  await dialog.getByLabel("Current password").fill(user.password);
  await dialog.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("Password changed")).toBeVisible();
  await expect(dialog).toHaveCount(0);

  // Notifications: mentions off, remembered; approvals can't be turned off.
  await settingsNav.getByRole("link", { name: "Notifications" }).click();
  const kinds = page.getByRole("list", { name: "Notifications you get" });
  await kinds.getByRole("checkbox", { name: /Mentions/ }).click();
  await expect(kinds.getByRole("checkbox", { name: /Changes waiting for your decision/ })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole("list", { name: "Notifications you get" }).getByRole("checkbox", { name: /Mentions/ })).not.toBeChecked();
  await expect(page.getByRole("list", { name: "Notifications you get" }).getByRole("checkbox", { name: /Assigned to you/ })).toBeChecked();
});

test("GitHub in Settings, and a project's repository by address while the app isn't set up", async ({ page }) => {
  const { key } = await signUpWithProject(page, "Kurepo", "KUR");
  const workspaceUrl = page.url().replace(/\/p\/.*$/, "");

  await page.goto(`${workspaceUrl}/settings/github`);
  await expect(page.getByText("The GitHub App isn't set up on this server")).toBeVisible();
  // A setup redirect that this browser didn't start comes back with an error, not an installation.
  const forged = await page.request.get("/api/github/setup?installation_id=1&setup_action=install&state=forged", {
    maxRedirects: 0,
  });
  expect(forged.status()).toBe(307);
  expect(forged.headers()["location"]).toContain("github_error=");

  await page.goto(`${workspaceUrl}/p/${key}/settings`);
  await page.getByRole("button", { name: "Connect from GitHub" }).click();
  await expect(page.getByText("needs the GitHub App, which isn't set up on this server yet", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Use an address instead" }).click();
  await page.getByLabel("Repository address").fill("https://gitlab.com/acme/kurepo");
  await page.getByRole("button", { name: "Link repository" }).click();
  await expect(page.getByText("Address only")).toBeVisible();
  await expect(page.getByRole("link", { name: "https://gitlab.com/acme/kurepo" })).toBeVisible();
});
