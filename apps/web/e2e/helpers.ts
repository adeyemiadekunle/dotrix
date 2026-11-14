import { expect, type Page } from "@playwright/test";

export const PASSWORD = "e2e-only-password-1234";

// Specs still written for the older screens (admin, pipelines, research), parked until rewritten.
export const NOT_WIRED = "Written for the older app; not rewritten for the current screens yet";

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
  await page.getByLabel("Name", { exact: true }).fill(user.name);
  await page.getByLabel("Email", { exact: true }).fill(user.email);
  await page.getByLabel("Password", { exact: true }).fill(user.password);
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

/** The workspace the page is in, from the API. */
export async function currentWorkspace(page: Page) {
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const workspaces = await (await page.request.get("/v1/workspaces")).json();
  const workspace = workspaces.find((item: { slug: string }) => item.slug === slug);
  if (!workspace) throw new Error("Workspace not found");
  return workspace as { id: string; slug: string };
}

const WRITE = { "X-Requested-With": "e2e" };

/** Signs up, creates a docs-only project through the API (project setup has its own flow tests) and opens its board. */
export async function signUpWithProject(page: Page, name = "Kumove", key = "KUM") {
  const user = await signUp(page);
  const workspace = await currentWorkspace(page);
  const created = await page.request.post(`/v1/workspaces/${workspace.id}/projects`, { headers: WRITE, data: { key, name, source: "docs_only" } });
  expect(created.status()).toBe(201);
  const project = (await created.json()) as { id: string };
  await page.goto(`/w/${workspace.slug}/p/${key}/board`);
  await expect(page.getByRole("navigation", { name: "Project" })).toBeVisible();
  return { user, key, workspace, project };
}

/** A task made through the API, as a colleague or an import would leave one. */
export async function createTask(page: Page, workspaceId: string, projectId: string, data: Record<string, unknown>) {
  const created = await page.request.post(`/v1/workspaces/${workspaceId}/projects/${projectId}/issues`, { headers: WRITE, data });
  expect(created.status()).toBe(201);
  return (await created.json()) as { id: string; key: string };
}

/** A mode is selected inside +; checking it must not change it or send a message. */
export async function expectComposerMode(page: Page, name: "Discuss" | "Plan" | "Build" | "Review") {
  const plus = page.getByRole("button", { name: /^(Project and mode|Mode)$/ });
  const menu = page.getByRole("dialog", { name: /^(Project and mode|Mode)$/ });
  if (!(await menu.isVisible())) await plus.click();
  await expect(menu.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
}
