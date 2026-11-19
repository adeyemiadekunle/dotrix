import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers";

const org = {
  id: "organisation-installation",
  installation_id: 111,
  account_login: "acme",
  account_type: "Organization",
  suspended: false,
  created_at: "2026-11-02T00:00:00Z",
};
const repo = {
  installation_ref: org.id,
  github_repo_id: 42,
  full_name: "acme/booking",
  private: true,
  default_branch: "main",
  html_url: "https://github.com/acme/booking",
  project_key: null,
};
async function start(page: Page) {
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "New project", exact: true }).click();
  await page.getByRole("radio", { name: "Start a new codebase", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByLabel("Project name", { exact: true }).fill("Booking");
  await page.getByLabel("Project key", { exact: true }).fill("BOOK");
  await page.getByLabel("Project goal", { exact: true }).fill("Help consultants schedule bookings.");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
}
async function review(page: Page) {
  await page.getByLabel("Repository owner", { exact: true }).selectOption(org.id);
  await page.getByLabel("Repository name", { exact: true }).fill("booking");
  await page.getByRole("button", { name: "Review repository", exact: true }).click();
}

test("organisation creation requires confirmation and a separate connection", async ({ page }) => {
  await signUp(page);
  await page.route("**/github", (route) => route.fulfill({ json: { configured: true, install_url: null, installations: [org] } }));
  const creations: unknown[] = [];
  let attached = 0;
  await page.route("**/github/repos", (route) => {
    if (route.request().method() === "POST") {
      creations.push(route.request().postDataJSON());
      return route.fulfill({ status: 201, json: repo });
    }
    return route.fulfill({ json: creations.length ? [repo] : [] });
  });
  page.on("request", (request) => {
    if (request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/repository")) attached++;
  });
  await start(page);
  await review(page);
  await expect(page.getByText("acme/booking", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Repository visibility", { exact: true })).toHaveValue("private");
  expect(creations).toEqual([]);
  await page.getByRole("button", { name: "Cancel creation", exact: true }).click();
  expect(creations).toEqual([]);
  await page.getByRole("button", { name: "Review repository", exact: true }).click();
  await page.getByRole("button", { name: "Confirm creation", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Repository created." })).toBeVisible();
  expect(creations).toEqual([{ installation_ref: org.id, name: "booking", private: true, description: "" }]);
  await expect(page.getByLabel("Repository", { exact: true })).toHaveValue(`${org.id}:42`);
  await expect(page.getByRole("button", { name: "Use repository", exact: true })).toBeEnabled();
  expect(attached).toBe(0);
});

test("a lost creation response recovers the repository without another create or attachment", async ({ page }) => {
  await signUp(page);
  await page.route("**/github", (route) => route.fulfill({ json: { configured: true, install_url: null, installations: [org] } }));
  let creations = 0;
  await page.route("**/github/repos", (route) => {
    if (route.request().method() === "POST") {
      creations++;
      return route.abort("failed");
    }
    return route.fulfill({ json: creations ? [repo] : [] });
  });
  await start(page);
  await review(page);
  await page.getByRole("button", { name: "Confirm creation", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Creation was not confirmed");
  await expect(page.getByRole("button", { name: "Confirm creation", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Check available repositories", exact: true }).click();
  await expect(page.getByRole("button", { name: "Review repository", exact: true })).toBeDisabled();
  await page.getByLabel("Repository", { exact: true }).selectOption(`${org.id}:42`);
  await expect(page.getByRole("button", { name: "Use repository", exact: true })).toBeEnabled();
  expect(creations).toBe(1);
  await page.reload();
  await expect(page.getByRole("option", { name: "acme/booking", exact: true })).toHaveCount(1);
  expect(creations).toBe(1);
});

test("personal accounts use GitHub creation and refresh instead of an unsupported in-app write", async ({ page }) => {
  await signUp(page);
  await page.route("**/github", (route) =>
    route.fulfill({ json: { configured: true, install_url: null, installations: [{ ...org, account_type: "User", account_login: "ada" }] } }),
  );
  await page.route("**/github/repos", (route) => route.fulfill({ json: [] }));
  await start(page);
  await expect(page.getByRole("link", { name: "create the repository on GitHub" })).toHaveAttribute("href", "https://github.com/new");
  await expect(page.getByText(/grant the GitHub App access/)).toBeVisible();
  await expect(page.getByLabel("Repository owner", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Refresh repositories", exact: true })).toBeEnabled();
});
