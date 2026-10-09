import { expect, test, type Page } from "@playwright/test";

import { PASSWORD, signUp } from "./helpers";

// Settings in a real workspace: each section reads and saves through the API.

const slugOf = (page: Page) => new URL(page.url()).pathname.split("/")[2]!;
const settings = (page: Page, sec: string) => page.goto(`/w/${slugOf(page)}/settings/${sec}`);

test("your profile: name and what you do are saved, and Members shows them", async ({ page }) => {
  await signUp(page);
  await settings(page, "profile");
  await page.getByLabel("Full name").fill("Ada Lovelace");
  await page.getByLabel("What you do").fill("Analyst");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByText("Profile saved")).toBeVisible();
  await expect(page.getByText("Not linked")).toBeVisible(); // GitHub, from the sign-in methods

  await page.reload();
  await expect(page.getByLabel("What you do")).toHaveValue("Analyst");
  await page.goto(`/w/${slugOf(page)}/members`);
  await expect(page.locator("tr", { hasText: "Ada Lovelace" })).toBeVisible();
});

test("where you're signed in: each browser is listed, and another one can be signed out", async ({ page, browser }) => {
  const user = await signUp(page);
  const other = await browser.newContext();
  const second = await other.newPage();
  await second.goto("/login");
  await second.getByLabel("Email").fill(user.email);
  await second.getByLabel("Password").fill(user.password);
  await second.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(second).toHaveURL(/\/w\//);

  await settings(page, "sessions");
  await expect(page.getByText("This browser")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByText("Signed out", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out", exact: true })).toHaveCount(0);
  await other.close();
});

test("change your password (a wrong current one is refused), and choose which notifications you get", async ({ page }) => {
  await signUp(page);
  await settings(page, "password");
  await page.getByLabel("Current password").fill("not-my-password-1");
  await page.getByLabel("New password", { exact: true }).fill("a-new-password-2026!");
  await page.getByLabel("Confirm new password").fill("a-new-password-2026!");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("That isn't your current password")).toBeVisible();
  await page.getByLabel("Current password").fill(PASSWORD);
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText("Password updated")).toBeVisible();

  await settings(page, "notif-email");
  await page.getByLabel("Email me").selectOption("daily");
  await settings(page, "notif-mentions");
  await page.getByLabel("Mentions").uncheck();
  await page.reload();
  await expect(page.getByLabel("Mentions")).not.toBeChecked();
  await settings(page, "notif-email");
  await expect(page.getByLabel("Email me")).toHaveValue("daily");
});

test("the CLI's sign-ins are listed with the sessions, and can be signed out; the old Devices address opens Sessions", async ({ page }) => {
  await signUp(page);
  // What `pmagent login` leaves behind: a token named for the device.
  await page.evaluate(() =>
    fetch("/v1/me/tokens", { method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "e2e" }, body: JSON.stringify({ name: "pmagent CLI on laptop" }) }),
  );
  await settings(page, "devices");
  await expect(page.locator("#main-content h1, .set-in h1").first()).toHaveText("Sessions");
  const row = page.locator(".srow", { hasText: "pmagent CLI on laptop" });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByText("The CLI isn't signed in anywhere.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Devices and tokens" })).toHaveCount(0);
});

test("agents: change a built-in's contract, then reset it; workspace rules are saved as versions", async ({ page }) => {
  await signUp(page);
  await settings(page, "agents");
  await page.getByText("Research Agent").first().click();
  await page.getByLabel("Description").fill("Finds and checks sources on the web.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/Saved as version \d+/)).toBeVisible();
  await expect(page.getByText("Customised").first()).toBeVisible();
  await page.getByRole("button", { name: "Reset to default" }).click();
  await page.locator(".modal").getByRole("button", { name: "Reset to default" }).click();
  await expect(page.getByText("Reset to default", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("Built-in").first()).toBeVisible();

  await settings(page, "rules");
  await page.getByLabel("Rules").fill("- Write in plain English.");
  await page.getByRole("button", { name: "Save", exact: true }).first().click();
  await expect(page.getByText("Rules saved (v1)")).toBeVisible();
});

test("GitHub says when the app isn't set up on this server", async ({ page }) => {
  await signUp(page);
  await settings(page, "github");
  await expect(page.getByText("The GitHub App isn't set up on this server yet")).toBeVisible();
});
