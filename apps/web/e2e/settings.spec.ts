import { expect, test, type Page } from "@playwright/test";

import { PASSWORD, signUp } from "./helpers";

// Settings in a real workspace: each section reads and saves through the API.

const slugOf = (page: Page) => new URL(page.url()).pathname.split("/")[2]!;
const settings = (page: Page, sec: string) => page.goto(`/w/${slugOf(page)}/settings/${sec}`);

test("Code Mode preference persists across settings reloads", async ({ page }) => {
  await signUp(page);
  await settings(page, "preferences");
  const toggle = page.getByRole("switch", { name: "Code Mode", exact: true });
  await expect(toggle).toBeChecked();
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  await page.reload();
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await page.reload();
  await expect(toggle).toBeChecked();
});

test("your profile: name and what you do are saved, and your profile page shows them", async ({ page }) => {
  await signUp(page);
  await settings(page, "profile");
  await page.getByLabel("Full name", { exact: true }).fill("Ada Lovelace");
  await page.getByLabel("What you do", { exact: true }).fill("Analyst");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Profile saved")).toBeVisible();
  await expect(page.getByText("Not linked")).toBeVisible(); // GitHub, from the sign-in methods

  await page.reload();
  await expect(page.getByLabel("What you do", { exact: true })).toHaveValue("Analyst");
  // A personal workspace has no Members page; your own profile page (the account menu's View profile) shows you.
  await page
    .getByRole("button", { name: /Ada Lovelace/ })
    .first()
    .click();
  await page.locator(".mi", { hasText: "View profile" }).click();
  await expect(page.locator("#main-content")).toContainText("Ada Lovelace");
  await expect(page.locator("#main-content")).toContainText("Analyst");
});

test("where you're signed in: each browser is listed, and another one can be signed out", async ({ page, browser }) => {
  const user = await signUp(page);
  const other = await browser.newContext();
  const second = await other.newPage();
  await second.goto("/login");
  await second.getByLabel("Email", { exact: true }).fill(user.email);
  await second.getByLabel("Password", { exact: true }).fill(user.password);
  await second.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(second).toHaveURL(/\/w\//);

  await settings(page, "sessions");
  await expect(page.getByText("This browser", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Signed out", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toHaveCount(0);
  await other.close();
});

test("change your password (a wrong current one is refused), and choose which notifications you get", async ({ page }) => {
  await signUp(page);
  await settings(page, "password");
  await page.getByLabel("Current password", { exact: true }).fill("not-my-password-1");
  await page.getByLabel("New password", { exact: true }).fill("a-new-password-2026!");
  await page.getByLabel("Confirm new password", { exact: true }).fill("a-new-password-2026!");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("That isn't your current password")).toBeVisible();
  await page.getByLabel("Current password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("Password updated")).toBeVisible();

  await settings(page, "notif-email");
  await page.getByLabel("Email me", { exact: true }).selectOption("daily");
  await settings(page, "notif-mentions");
  await page.getByLabel("Mentions", { exact: true }).uncheck();
  await page.reload();
  await expect(page.getByLabel("Mentions", { exact: true })).not.toBeChecked();
  await settings(page, "notif-email");
  await expect(page.getByLabel("Email me", { exact: true })).toHaveValue("daily");
});

test("tokens under Sessions: the CLI's sign-in is listed, a new one is shown once, both revoke; the old Devices address opens Sessions", async ({ page }) => {
  await signUp(page);
  // What `dotrix login` leaves behind: a token named for the device.
  await page.evaluate(() =>
    fetch("/v1/me/tokens", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "e2e" },
      body: JSON.stringify({ name: "dotrix CLI on laptop" }),
    }),
  );
  await settings(page, "devices");
  await expect(page.locator(".set-in h1")).toHaveText("Sessions");
  await expect(page.getByRole("heading", { name: "Tokens" })).toBeVisible();
  await expect(page.locator(".srow", { hasText: "dotrix CLI on laptop" })).toBeVisible();

  await page.getByRole("button", { name: "New token" }).click();
  await page.getByRole("dialog").locator("input").fill("CI");
  await page.getByRole("dialog").locator("input").press("Enter");
  await expect(page.getByText("copy it now, it isn't shown again")).toBeVisible();
  await expect(page.locator("code", { hasText: /^dtx_/ })).toBeVisible();

  await page.locator(".srow", { hasText: "CI" }).getByRole("button", { name: "Revoke" }).click();
  await page.locator(".srow", { hasText: "dotrix CLI on laptop" }).getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText("No tokens.")).toBeVisible();
});

test("agents: change a built-in's contract, then reset it; workspace rules are saved as versions", async ({ page }) => {
  await signUp(page);
  await settings(page, "agents");
  await page.locator("#main-content .mini", { hasText: "@research" }).click();
  await page.getByLabel("Additional instructions", { exact: true }).fill("Finds and checks sources on the web.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(/Saved as version \d+/)).toBeVisible();
  await expect(page.getByText("Customised").first()).toBeVisible();
  await page.getByRole("button", { name: "Reset to default" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reset to default" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Reset to default", { exact: true })).toBeVisible();
  await expect(page.getByText("Built-in").first()).toBeVisible();

  await settings(page, "rules");
  await page.getByLabel("Rules", { exact: true }).fill("- Write in plain English.");
  await page.getByRole("button", { name: "Save", exact: true }).first().click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Rules saved (v1)")).toBeVisible();
});

test("agents: an owner lets one write documents without asking, and the workspace can pause it", async ({ page }) => {
  await signUp(page);
  await settings(page, "agents");
  await page.locator("#main-content .mini", { hasText: "@product" }).click();
  await page.getByLabel("Write documents without asking", { exact: true }).selectOption("allow");
  await expect(page.getByText("Changes go through without anyone approving them.")).toBeVisible();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(/Saved as version \d+/)).toBeVisible();
  await page.reload();
  await page.locator("#main-content .mini", { hasText: "@product" }).click();
  await expect(page.getByLabel("Write documents without asking", { exact: true })).toHaveValue("allow");

  await settings(page, "agents");
  await page.getByLabel("Pause changes without approval", { exact: true }).check();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Agents ask before every change")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Pause changes without approval", { exact: true })).toBeChecked();
});

test("legacy model settings connects only your own key, and an agent can use a smaller model", async ({ page }) => {
  await signUp(page);
  await settings(page, "models");
  await expect(page.locator(".set-in h1")).toHaveText("Your models");
  const anthropic = page.locator(".srow-wrap", { hasText: "Anthropic" });
  await anthropic.getByRole("button", { name: "Connect" }).click();
  await page.getByLabel("Anthropic API key", { exact: true }).fill("sk-ant-e2e-" + "x".repeat(30) + "AB12");
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Your Anthropic key is saved")).toBeVisible();
  await expect(anthropic.getByText(/Connected · key ending AB12/)).toBeVisible();
  await expect(page.getByText("sk-ant-e2e")).toHaveCount(0);

  // Echo (documentation) doesn't need the biggest model.
  await settings(page, "agents");
  await page.locator("#main-content .mini", { hasText: "@documentation" }).click();
  await page.getByLabel("Model", { exact: true }).selectOption("anthropic:claude-haiku-5-5");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(/Saved as version \d+/)).toBeVisible();
  await page.reload();
  await page.locator("#main-content .mini", { hasText: "@documentation" }).click();
  await expect(page.getByLabel("Model", { exact: true })).toHaveValue("anthropic:claude-haiku-5-5");

  await settings(page, "my-models");
  await page.locator(".srow-wrap", { hasText: "Anthropic" }).getByRole("button", { name: "Remove" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Your Anthropic key is removed")).toBeVisible();
  await page.reload();
  await expect(anthropic.getByRole("button", { name: "Connect", exact: true })).toBeVisible();
});

test("your own models and agents: a key of your own, a default model, and how you like Lyra to work", async ({ page }) => {
  await signUp(page);
  await settings(page, "my-models");
  const anthropic = page.locator(".srow-wrap", { hasText: "Anthropic" });
  await anthropic.getByRole("button", { name: "Connect" }).click();
  await page.getByLabel("Anthropic API key", { exact: true }).fill("sk-ant-mine-" + "m".repeat(30) + "ME42");
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Your Anthropic key is saved")).toBeVisible();
  await expect(anthropic.getByText(/key ending ME42/)).toBeVisible();
  await page.getByLabel("Your default model", { exact: true }).selectOption("anthropic:claude-haiku-5-5");
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Default model saved")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Your default model", { exact: true })).toHaveValue("anthropic:claude-haiku-5-5");

  await settings(page, "my-agents");
  await page.getByLabel("How you like Lyra to work", { exact: true }).fill("Short stories, British English.");
  await page.locator(".sblock", { hasText: "@product" }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Lyra saved for you")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("How you like Lyra to work", { exact: true })).toHaveValue("Short stories, British English.");
});

test("GitHub says when the app isn't set up on this server", async ({ page }) => {
  await signUp(page);
  await settings(page, "github");
  await expect(page.getByText("The GitHub App isn't set up on this server yet")).toBeVisible();
});
