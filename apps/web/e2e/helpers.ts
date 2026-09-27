import { expect, type Page } from "@playwright/test";

export const PASSWORD = "e2e-only-password-1234";

let counter = 0;

/** A fresh account per test (the e2e database is shared by the run). */
export function newUser(name = "Ada Tester") {
  counter += 1;
  const tag = `${Date.now().toString(36)}${counter}`;
  return { name, email: `e2e-${tag}@example.com`, password: PASSWORD };
}

export async function signUp(page: Page, user = newUser()) {
  await page.goto("/signup");
  await page.getByLabel("Name").fill(user.name);
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/w\/personal-/);
  return user;
}

/** Signs up, then creates a docs-only project; lands on its board. Returns the project key. */
export async function signUpWithProject(page: Page, name = "Kumove", key = "KUM") {
  const user = await signUp(page);
  await page.getByRole("link", { name: "New project" }).first().click();
  await page.getByText("Documents only", { exact: true }).click();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Key").fill(key);
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/p/${key}/board`));
  return { user, key };
}
