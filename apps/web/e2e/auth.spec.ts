import { expect, test } from "@playwright/test";

import { newUser, signUp } from "./helpers";

test("signed-out visitors are sent to sign in, and come back afterwards", async ({ page }) => {
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings/);
});

test("sign up, sign out, and sign back in", async ({ page }) => {
  const user = await signUp(page, newUser("Grace Hopper"));
  await expect(page.getByText(`Confirm your email address using the link we sent to ${user.email}`)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  await page.getByRole("button", { name: /Grace Hopper/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/settings");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password")).toBeVisible();

  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("definition").filter({ hasText: user.email })).toBeVisible();
});

test("the theme follows the choice in settings and survives a reload", async ({ page }) => {
  await signUp(page);
  await page.goto("/settings");
  await page.getByText("Dark", { exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByText("Light", { exact: true }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});
