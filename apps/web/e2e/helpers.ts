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
  // Independent workspace tests opt out of first-account setup; onboarding has its own flow tests.
  await page.goto("/signup?next=%2F");
  await page.getByLabel("Name").fill(user.name);
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Create account" }).click();
  // Explicit return destinations bypass first-account setup for independent workspace tests.
  await expect(page).toHaveURL(/\/w\/[^/]+$/);
  return user;
}

/** Signs up, then creates a docs-only project (it opens on its Overview) and goes to its board. Returns the project key. */
export async function signUpWithProject(page: Page, name = "Kumove", key = "KUM") {
  const user = await signUp(page);
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  await page.getByLabel("Project name", { exact: true }).fill(name);
  await page.getByLabel("Project key", { exact: true }).fill(key);
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await page.getByRole("button", { name: "Continue with documents only" }).click();
  await page.getByRole("button", { name: /^(Continue|Set up models later)$/ }).click();
  await page.getByRole("link", { name: "Open project", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/p/${key}/overview`));
  await page.getByRole("navigation", { name: "Project" }).getByRole("link", { name: "Board", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/p/${key}/board`));
  return { user, key };
}

/** Why a spec of the API-backed workspace pages is parked: /w/… shows the seeded UI until
 * each screen is wired to the API (CLAUDE.md). Un-park a spec
 * when its screens are wired, updating it for their markup. */
export const NOT_WIRED = "the workspace runs on seeded data until this screen is wired to the API";
