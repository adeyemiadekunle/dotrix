import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("an idea needs only a working title and opens an editable Nova discussion without GitHub", async ({ page }) => {
  await signUp(page);
  const githubRequests: string[] = [];
  const agentRequests: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (/\/github(?:\/repos)?$/.test(path)) githubRequests.push(path);
    if (request.method() === "POST" && path.endsWith("/agent/runs")) agentRequests.push(path);
  });
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  for (const name of ["Explore an idea", "Start a new codebase", "Connect an existing repository"])
    await expect(page.getByRole("radio", { name, exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "Explore an idea", exact: true }).check();
  await page.getByLabel("Project name", { exact: true }).fill("Booking concept");
  await page.getByLabel("Project key", { exact: true }).fill("IDEA");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect your model", exact: true })).toBeVisible();
  const savedUrl = page.url();
  const saved = new URL(savedUrl);
  expect(saved.searchParams.get("intent")).toBe("idea");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Connect your model", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^(Continue|Set up models later)$/ }).click();
  await expect(page.getByRole("heading", { name: "Your idea has a home", exact: true })).toBeVisible();
  const href = await page.getByRole("link", { name: "Explore with Nova", exact: true }).getAttribute("href");
  expect(href).not.toContain("Booking");
  const project = await page.evaluate(async ({ workspace, project }) => (await fetch(`/v1/workspaces/${workspace}/projects/${project}`)).json(), {
    workspace: saved.searchParams.get("workspace"),
    project: saved.searchParams.get("project"),
  });
  expect(project).toMatchObject({ name: "Booking concept", source: "docs_only", description: "", repo_url: null });
  await page.getByRole("link", { name: "Explore with Nova", exact: true }).click();
  await expect(page.getByLabel("Message", { exact: true })).toHaveValue(/clarifying the problem, intended users, constraints and uncertainties/);
  await expect(page.getByRole("button", { name: "Project and mode", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Mode:/ })).toHaveCount(0); // Discuss: no mode chip
  expect(githubRequests).toEqual([]);
  expect(agentRequests).toEqual([]);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  await page.goto(`/w/${slug}/p/IDEA/overview`);
  await page.getByRole("link", { name: "Connect repository", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("project")).toBe(project.id);
});

test("new codebases require a goal before repository setup and restore their saved intention", async ({ page }) => {
  await signUp(page);
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  await page.getByRole("radio", { name: "Start a new codebase", exact: true }).check();
  await page.getByLabel("Project name", { exact: true }).fill("New booking app");
  await page.getByLabel("Project key", { exact: true }).fill("NEW");
  await expect(page.getByRole("button", { name: "Create project", exact: true })).toBeDisabled();
  await page.getByLabel("Project goal", { exact: true }).fill("Help independent consultants schedule bookings.");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const saved = new URL(page.url());
  const tampered = new URL(saved);
  tampered.searchParams.set("intent", "idea");
  tampered.searchParams.set("step", "project");
  await page.goto(tampered.href);
  await expect(page.getByRole("radio", { name: "Start a new codebase", exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: "Start a new codebase", exact: true })).toBeDisabled();
  await expect(page.getByText("Help independent consultants schedule bookings.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create project", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Continue setup", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Continue with documents only" }).click();
  await page.getByRole("button", { name: /^(Continue|Set up models later)$/ }).click();
  const href = await page.getByRole("link", { name: "Plan with Nova", exact: true }).getAttribute("href");
  expect(href).not.toContain("consultants");
  const project = await page.evaluate(async ({ workspace, project }) => (await fetch(`/v1/workspaces/${workspace}/projects/${project}`)).json(), {
    workspace: saved.searchParams.get("workspace"),
    project: saved.searchParams.get("project"),
  });
  expect(project).toMatchObject({ source: "new_repo", description: "Help independent consultants schedule bookings.", repo_url: null });
  await expect(page.getByRole("region", { name: "Project readiness", exact: true })).toContainText("Connect a GitHub repository before implementation");
});

test("existing repositories start with GitHub selection and require confirmation before attachment", async ({ page }) => {
  await signUp(page);
  await page.route("**/github", (route) => route.fulfill({ json: { configured: true, install_url: null, installations: [] } }));
  await page.route("**/github/repos", (route) =>
    route.fulfill({
      json: [
        {
          installation_ref: "test-installation",
          github_repo_id: 42,
          full_name: "acme/existing",
          private: true,
          default_branch: "main",
          html_url: "https://github.com/acme/existing",
          project_key: null,
        },
      ],
    }),
  );
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  await page.getByRole("radio", { name: "Connect an existing repository", exact: true }).check();
  await page.getByLabel("Project name", { exact: true }).fill("Existing system");
  await page.getByLabel("Project key", { exact: true }).fill("EXIST");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const saved = new URL(page.url());
  expect(saved.searchParams.get("intent")).toBe("existing");
  const attachments: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/repository")) attachments.push(request.url());
  });
  await page.getByLabel("Repository", { exact: true }).selectOption({ label: "acme/existing" });
  await expect(page.getByRole("button", { name: "Use repository", exact: true })).toBeEnabled();
  const project = await page.evaluate(async ({ workspace, project }) => (await fetch(`/v1/workspaces/${workspace}/projects/${project}`)).json(), {
    workspace: saved.searchParams.get("workspace"),
    project: saved.searchParams.get("project"),
  });
  expect(project).toMatchObject({ source: "existing_repo", repo_url: null });
  expect(attachments).toEqual([]);
  await page.route("**/repository", (route) => route.fulfill({ status: 503, json: { detail: "GitHub temporarily unavailable" } }));
  const submitted = page.waitForRequest((request) => request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/repository"));
  await page.getByRole("button", { name: "Use repository", exact: true }).click();
  const request = await submitted;
  expect(new URL(request.url()).pathname).toBe(`/v1/workspaces/${saved.searchParams.get("workspace")}/projects/${project.id}/repository`);
  expect(request.postDataJSON()).toEqual({ installation_ref: "test-installation", github_repo_id: 42 });
  await expect(page.getByRole("alert")).toContainText("GitHub temporarily unavailable");
  expect(new URL(page.url()).searchParams.get("project")).toBe(project.id);
});
