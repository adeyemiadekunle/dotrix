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

/** Explicitly create a separate team; the person's personal workspace stays private. */
export async function createOrganisation(page: Page, name = "Test organisation") {
  const response = await page.request.post("/v1/workspaces", {
    headers: { "X-Requested-With": "e2e" },
    data: { kind: "organization", name },
  });
  expect(response.status()).toBe(201);
  const workspace = await response.json();
  await page.goto(`/w/${workspace.slug}`);
  return workspace;
}

/** Existing projects move explicitly; workspace kinds never change. */
export async function moveProjectToOrganisation(page: Page, projectKey: string, name: string) {
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const workspaces = await (await page.request.get("/v1/workspaces")).json();
  const source = workspaces.find((workspace: { slug: string }) => workspace.slug === slug);
  if (!source) throw new Error("Source workspace not found");
  const projects = await (await page.request.get(`/v1/workspaces/${source.id}/projects`)).json();
  const project = projects.find((item: { key: string }) => item.key === projectKey);
  if (!project) throw new Error("Source project not found");
  const target = await createOrganisation(page, name);
  const moved = await page.request.post(`/v1/workspaces/${source.id}/projects/${project.id}/move`, {
    headers: { "X-Requested-With": "e2e" },
    data: { workspace_id: target.id },
  });
  expect(moved.status()).toBe(200);
  await page.goto(`/w/${target.slug}/p/${projectKey}/board`);
  return target;
}

/** Signs up, then creates a docs-only project (it opens on its Overview) and goes to its board. Returns the project key. */
export async function signUpWithProject(page: Page, name = "Kumove", key = "KUM") {
  const user = await signUp(page);
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  await page.getByRole("radio", { name: "Explore an idea", exact: true }).check();
  await page.getByLabel("Project name", { exact: true }).fill(name);
  await page.getByLabel("Project key", { exact: true }).fill(key);
  await page.getByRole("button", { name: "Create project", exact: true }).click();
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
