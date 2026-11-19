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
  await expect(page.getByRole("heading", { name: "Set up your profile", exact: true })).toBeVisible();
  await expect(page.getByLabel("Your name", { exact: true })).toHaveValue(person.name);
  await expect(page.getByRole("button", { name: "Setting up for a team?", exact: true })).toBeVisible();
  const steps = page.getByRole("list", { name: "Onboarding progress", exact: true });
  await expect(steps.getByRole("listitem")).toHaveCount(6);
  await expect(steps.locator('[aria-current="step"]')).toContainText("Profile");
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How do you want to start?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeDisabled();
  await page.getByRole("radio", { name: "Connect an existing repository", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
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
  await expect(page.getByRole("heading", { name: "Your project is saved" })).toBeVisible();
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
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await page.getByRole("radio", { name: "Connect an existing repository", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
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
  await page.getByRole("button", { name: "Setting up for a team?", exact: true }).click();
  await page.getByLabel("Organisation name", { exact: true }).fill("Delivery team");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How do you want to start?" })).toBeVisible();
  await page.getByRole("radio", { name: "Connect an existing repository", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Project access", { exact: true })).toBeVisible(); // a team's project chooses who sees it
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

test("later projects use the shared setup in the selected workspace and recover a lost save response", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const workspace = await page.evaluate(
    async (slug) => (await (await fetch("/v1/workspaces")).json()).find((item: { slug: string }) => item.slug === slug),
    slug,
  );
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How do you want to start?", exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("workspace")).toBe(workspace.id);
  await page.getByRole("radio", { name: "Connect an existing repository", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Create a project", exact: true })).toBeVisible();
  await page.getByLabel("Project name", { exact: true }).fill("Saved once");
  await page.getByLabel("Project key", { exact: true }).fill("ONCE");
  await page.getByLabel("Description (optional)", { exact: true }).fill("The server must confirm this project.");
  await expect(page.getByLabel("Project access", { exact: true })).toHaveCount(0); // a personal workspace is yours alone
  let posts = 0;
  await page.route("**/projects", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    await route.abort("failed"); // Save succeeded, but the browser never received its confirmation.
  });
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByText(/A project with this key is already saved/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Create project", exact: true })).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Create a project", exact: true })).toBeVisible();
  await page.getByLabel("Continue setting up an existing project", { exact: true }).selectOption({ label: "Saved once" });
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const savedUrl = page.url();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  expect(page.url()).toBe(savedUrl);
  expect(new URL(savedUrl).searchParams.get("mode")).toBe("project");
  await page.getByRole("button", { name: "Continue with documents only" }).click();
  await page.getByRole("button", { name: /^(Continue|Set up models later)$/ }).click();
  await page.getByRole("link", { name: "Open project", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/w/${slug}/p/ONCE/overview`));
  const projects = await page.evaluate(async (id) => await (await fetch(`/v1/workspaces/${id}/projects`)).json(), workspace.id);
  expect(projects).toHaveLength(1);
  expect(projects[0]).toMatchObject({ key: "ONCE", access: "workspace", description: "The server must confirm this project." });
  expect(posts).toBe(1);
});

test("signed-out setup retains its saved workspace and project through sign-in", async ({ page, browser }) => {
  const person = await signUp(page);
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  await page.getByRole("radio", { name: "Connect an existing repository", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Project name", { exact: true }).fill("Resume setup");
  await page.getByLabel("Project key", { exact: true }).fill("RESUME");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const saved = new URL(page.url());
  const context = await browser.newContext();
  const visitor = await context.newPage();
  await visitor.goto(saved.href);
  const login = new URL((await visitor.getByRole("link", { name: "Sign in", exact: true }).getAttribute("href")) ?? "", saved.origin);
  expect(login.searchParams.get("next")).toBe(saved.pathname + saved.search);
  await visitor.getByRole("link", { name: "Sign in", exact: true }).click();
  await visitor.getByLabel("Email", { exact: true }).fill(person.email);
  await visitor.getByLabel("Password", { exact: true }).fill(person.password);
  await visitor.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(visitor.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  expect(visitor.url()).toBe(saved.href);
  await context.close();
});

test("new invitees join the intended project without creating a personal project", async ({ page, browser }) => {
  await signUp(page);
  const setup = await page.evaluate(async () => {
    const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const team = await (
      await fetch("/v1/workspaces", { method: "POST", headers, body: JSON.stringify({ name: "Inviting team", kind: "organization" }) })
    ).json();
    const project = await (
      await fetch(`/v1/workspaces/${team.id}/projects`, {
        method: "POST",
        headers,
        body: JSON.stringify({ name: "Team work", key: "JOIN", source: "docs_only" }),
      })
    ).json();
    const link = await (await fetch(`/v1/workspaces/${team.id}/invites/links`, { method: "POST", headers, body: JSON.stringify({ role: "member" }) })).json();
    return { team, project, link };
  });
  const context = await browser.newContext();
  const member = await context.newPage();
  const destination = `/w/${setup.team.slug}/p/JOIN/board`;
  const inviteUrl = new URL(setup.link.url, page.url());
  inviteUrl.searchParams.set("next", destination);
  await member.goto(inviteUrl.href);
  await expect(member.getByRole("heading", { name: "Join Inviting team", exact: true })).toBeVisible();
  await member.getByRole("link", { name: "Create an account to join", exact: true }).click();
  const person = newUser("New teammate");
  await member.getByLabel("Name", { exact: true }).fill(person.name);
  await member.getByLabel("Email", { exact: true }).fill(person.email);
  await member.getByLabel("Password", { exact: true }).fill(person.password);
  await member.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(member.getByRole("button", { name: "Accept and join", exact: true })).toBeVisible();
  await member.getByRole("button", { name: "Accept and join", exact: true }).click();
  await expect(member).toHaveURL(new URL(destination, page.url()).href);
  const personalCount = await member.evaluate(async () => {
    const workspaces = await (await fetch("/v1/workspaces")).json();
    const personal = workspaces.find((workspace: { kind: string }) => workspace.kind === "personal");
    return (await (await fetch(`/v1/workspaces/${personal.id}/projects`)).json()).length;
  });
  expect(personalCount).toBe(0);
  await member.goto(`/onboarding?workspace=${setup.team.id}&mode=project`);
  await expect(member.getByRole("heading", { name: "Open your team workspace", exact: true })).toBeVisible();
  await expect(member.getByRole("button", { name: "Create project", exact: true })).toHaveCount(0);
  await context.close();
});

test("a lost team-workspace save response resumes the saved team instead of creating another", async ({ page }) => {
  await signUp(page);
  await page.goto("/onboarding?mode=project&team=1");
  let posts = 0;
  await page.route("**/v1/workspaces", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    await route.abort("failed");
  });
  await page.getByLabel("Team workspace name", { exact: true }).fill("Recovered team");
  await page.getByRole("button", { name: "Create team workspace", exact: true }).click();
  await expect(page.getByText("A team workspace with this name is already saved.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create team workspace", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Use saved team workspace", exact: true }).click();
  await page.getByRole("radio", { name: "Connect an existing repository", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Project name", { exact: true }).fill("Recovered project");
  await page.getByLabel("Project key", { exact: true }).fill("RECOVER");
  await expect(page.getByRole("button", { name: "Create project", exact: true })).toBeEnabled();
  await page.getByLabel("Project key", { exact: true }).press("Enter");
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const state = await page.evaluate(async (id) => {
    const workspaces = await (await fetch("/v1/workspaces")).json();
    const projects = await (await fetch(`/v1/workspaces/${id}/projects`)).json();
    return {
      teams: workspaces.filter((workspace: { kind: string }) => workspace.kind === "organization").length,
      keys: projects.map((project: { key: string }) => project.key),
    };
  }, new URL(page.url()).searchParams.get("workspace"));
  expect(state).toEqual({ teams: 1, keys: ["RECOVER"] });
  expect(posts).toBe(1);
});

test("an idea skips GitHub and a new codebase needs its goal, each with optional setup skipped", async ({ page }) => {
  await signUp(page);
  await page.route("**/github", (route) => route.fulfill({ json: { configured: false, install_url: null, installations: [] } }));
  // An idea: no repository step at all, the model can wait, and it lands on a useful first action.
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await page.getByRole("radio", { name: "Explore an idea", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const progress = page.getByRole("list", { name: "Onboarding progress", exact: true });
  await expect(progress).not.toContainText("GitHub");
  await page.getByLabel("Project name", { exact: true }).fill("Recipe app");
  await expect(page.getByLabel("Project key", { exact: true })).toHaveValue("RECIPEAPP");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect your model", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^(Continue|Set up models later)$/ }).click(); // Continue when a model is already connected
  await expect(page.getByRole("heading", { name: "Your idea has a home", exact: true })).toBeVisible();
  await expect(page.getByText(/^(Explore with Nova|Set up Nova)$/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open project", exact: true })).toHaveAttribute("href", /\/p\/RECIPEAPP\/overview$/);
  // A new codebase: the goal is required, then GitHub comes next and can be skipped.
  const workspace = new URL(page.url()).searchParams.get("workspace")!;
  await page.goto(`/onboarding?mode=project&workspace=${workspace}`);
  await page.getByRole("radio", { name: "Start a new codebase", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Project name", { exact: true }).fill("Billing service");
  await expect(page.getByRole("button", { name: "Create project", exact: true })).toBeDisabled();
  await page.getByLabel("Project goal", { exact: true }).fill("Invoices and refunds for the shop.");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Continue with documents only", exact: true }).click();
  await page.getByRole("button", { name: /^(Continue|Set up models later)$/ }).click(); // Continue when a model is already connected
  await expect(page.getByRole("heading", { name: "Your project is saved", exact: true })).toBeVisible();
  const keys = await page.evaluate(
    async (id) => (await (await fetch(`/v1/workspaces/${id}/projects`)).json()).map((p: { key: string; source: string }) => `${p.key}:${p.source}`).sort(),
    workspace,
  );
  expect(keys).toEqual(["BILLINGSER:new_repo", "RECIPEAPP:docs_only"]);
});
