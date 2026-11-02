import { expect, test } from "@playwright/test";
import { newUser, signUp } from "./helpers";

test("new accounts save a first project, resume setup and connect a personal model without recreating the workspace", async ({ page }) => {
  const person = newUser();
  await page.route("**/github", (route) => route.fulfill({ json: { configured: false, install_url: null, installations: [] } }));
  await page.goto("/signup");
  await page.getByLabel("Name", { exact: true }).fill(person.name);
  await page.getByLabel("Email", { exact: true }).fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(person.password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByRole("heading", { name: "Create your first project" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create project", exact: true })).toBeDisabled();
  await page.getByLabel("Project name", { exact: true }).fill("Customer portal");
  await page.getByLabel("Project key", { exact: true }).fill("PORTAL");
  await page.route(
    "**/projects",
    (route) =>
      route.request().method() === "POST" ? route.fulfill({ status: 503, json: { detail: "Project storage temporarily unavailable" } }) : route.continue(),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("temporarily unavailable");
  await expect(page.getByRole("heading", { name: "Create your first project" })).toBeVisible();
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const location = page.url();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  expect(page.url()).toBe(location);
  await page.getByRole("button", { name: "Continue with documents only" }).click();
  await expect(page.getByRole("heading", { name: "Connect your model", exact: true })).toBeVisible();
  await page.getByLabel("Model provider", { exact: true }).selectOption("openai");
  const fakeKey = "test-personal-onboarding-key-only";
  await page.getByLabel("Model API key", { exact: true }).fill(fakeKey);
  const saved = page.waitForResponse((response) => response.url().endsWith("/me/model-keys/openai") && response.request().method() === "PUT");
  await page.getByRole("button", { name: "Save personal key", exact: true }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByLabel("Model API key", { exact: true })).toHaveValue("");
  expect(page.url()).not.toContain(fakeKey);
  const stored = await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]));
  expect(stored).not.toContain(fakeKey);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your project is ready" })).toBeVisible();
  await page.getByRole("link", { name: "Open project", exact: true }).click();
  await expect(page).toHaveURL(/\/p\/PORTAL\/overview/);
  const counts = await page.evaluate(async () => {
    const ws = await (await fetch("/v1/workspaces")).json();
    const projects = await (await fetch(`/v1/workspaces/${ws[0].id}/projects`)).json();
    return { workspaces: ws.length, projects: projects.map((project: { key: string }) => project.key) };
  });
  expect(counts).toEqual({ workspaces: 1, projects: ["PORTAL"] });
});

test("GitHub installation returns to the saved onboarding project", async ({ page }) => {
  await signUp(page);
  await page.route("**/github", (route) =>
    route.fulfill({ json: { configured: true, install_url: "https://github.com/apps/test/installations/new", installations: [] } }),
  );
  await page.goto("/onboarding");
  await page.getByLabel("Project name", { exact: true }).fill("GitHub project");
  await page.getByLabel("Project key", { exact: true }).fill("GITHUB");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const saved = new URL(page.url());
  let returnPath = "";
  await page.route("**/api/github/install?**", (route) => {
    returnPath = new URL(route.request().url()).searchParams.get("next") ?? "";
    return route.fulfill({ status: 302, headers: { Location: returnPath } });
  });
  await page.getByRole("button", { name: "Connect GitHub App", exact: true }).click();
  await expect.poll(() => returnPath).toBe(saved.pathname + saved.search);
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("project")).toBe(saved.searchParams.get("project"));
});

test("team workspace creation is explicit and its saved project resumes after refresh", async ({ page }) => {
  await signUp(page);
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Create a team workspace", exact: true }).click();
  await page.getByLabel("Team workspace name", { exact: true }).fill("Delivery team");
  await page.getByRole("button", { name: "Create team workspace", exact: true }).click();
  await expect(page.getByRole("button", { name: "Create a team workspace", exact: true })).toBeVisible();
  await page.getByLabel("Project name", { exact: true }).fill("Team project");
  await page.getByLabel("Project key", { exact: true }).fill("TEAM");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const saved = new URL(page.url());
  const state = await page.evaluate(async (workspaceId) => {
    const ws = await (await fetch("/v1/workspaces")).json();
    const projects = await (await fetch(`/v1/workspaces/${workspaceId}/projects`)).json();
    return { kinds: ws.map((item: { kind: string }) => item.kind).sort(), projects: projects.map((item: { key: string }) => item.key) };
  }, saved.searchParams.get("workspace"));
  expect(state).toEqual({ kinds: ["organization", "personal"], projects: ["TEAM"] });
});
