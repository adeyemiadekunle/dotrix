import { expect, test } from "@playwright/test";

import { newUser, signUp } from "./helpers";

// The workspace runs on seeded data until the API is wired (CLAUDE.md, the Gr8r plan), so there
// is no sign-in guard in front of it yet; the sign-in pages themselves still go through the API.
test.fixme("signed-out visitors are sent to sign in, and come back afterwards", async ({ page }) => {
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings/);
});

test("sign up, then sign in: a wrong password is refused, the right one opens the workspace", async ({ page }) => {
  const user = await signUp(page, newUser("Grace Hopper"));
  await page.context().clearCookies();

  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password")).toBeVisible();

  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/w\/[^/]+$/);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
});

test("the theme follows the choice in settings and survives a reload", async ({ page }) => {
  await page.goto("/w/dotrix/settings/appearance");
  await page.getByRole("radio", { name: /Dark/ }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("radio", { name: /Light/ }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("ask for a sign-in link, and a used or made-up link is refused", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Email me a sign-in link instead" }).click();
  await expect(page.getByLabel("Password")).toHaveCount(0);
  await page.getByLabel("Email").fill("someone@example.com");
  await page.getByRole("button", { name: "Email me a sign-in link", exact: true }).click();
  await expect(page.getByText("Check your email")).toBeVisible();
  await expect(page.getByText("We sent a link to someone@example.com. It signs you in, or creates your account")).toBeVisible();

  // The sign-up page offers the same thing.
  await page.goto("/signup");
  await page.getByRole("link", { name: "Sign up with an email link instead" }).click();
  await expect(page.getByText("Sign in or sign up by email")).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveCount(0);

  // A sign-up link that isn't real (or was used, or expired) is explained.
  await page.goto("/signup/finish?token=not-a-real-token");
  await expect(page.getByText("This link is invalid or has expired")).toBeVisible();

  // The link's page asks for a click (mail scanners open links); a bad token is explained.
  await page.goto("/magic-link?token=not-a-real-token");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("This link is invalid or has expired. Ask for a new link")).toBeVisible();
});
