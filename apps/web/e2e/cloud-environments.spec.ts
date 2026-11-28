import { expect, test } from "@playwright/test";
import { pickSelect, signUp } from "./helpers";

test("project environments persist without running scripts and stay separate", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const workspace = (await (await page.request.get("/v1/workspaces")).json())[0];
  const projects = [];
  for (const key of ["ENVONE", "ENVTWO"]) {
    const response = await page.request.post(`/v1/workspaces/${workspace.id}/projects`, {
      headers: { "X-Requested-With": "e2e" },
      data: { key, name: key, source: "docs_only" },
    });
    expect(response.status()).toBe(201);
    projects.push(await response.json());
  }
  await page.goto(`/w/${slug}/settings/sandbox`);
  const scope = page.getByLabel("Applies to", { exact: true });
  await pickSelect(page, scope, projects[0].name);
  await page.getByRole("button", { name: "Edit environment", exact: true }).click();

  // One form: name, network access, setup script, variables, and the rest under More settings.
  const sheet = page.getByRole("dialog", { name: "Edit environment" });
  await sheet.getByLabel("Name", { exact: true }).fill("Python environment");
  await sheet.getByRole("button", { name: "Network access", exact: true }).click();
  const network = page.getByRole("dialog", { name: "Network access" });
  await network.getByRole("checkbox", { name: /^PyPI/ }).check();
  await network.getByLabel("Other hosts", { exact: true }).fill("api.example.com");
  await network.getByRole("button", { name: "Done", exact: true }).click();
  await expect(sheet.getByRole("button", { name: "Network access", exact: true })).toContainText("PyPI, 1 host");
  await sheet.getByLabel("Setup script", { exact: true }).fill("python3 --version");
  // A line that isn't KEY=value is caught before saving.
  const variables = sheet.getByLabel("Environment variables", { exact: true });
  await variables.fill("LOG_LEVEL debug");
  await expect(sheet.getByText("Line 1 isn't KEY=value")).toBeVisible();
  await expect(sheet.getByRole("button", { name: "Save changes", exact: true })).toBeDisabled();
  await variables.fill("# for tests\nLOG_LEVEL=debug");
  await sheet.getByRole("button", { name: "More settings", exact: true }).click();
  await sheet.getByLabel("Verification command", { exact: true }).fill("python3 -B -m unittest");
  const imageSelect = sheet.getByLabel("Coding image", { exact: true });
  await imageSelect.click();
  const imageOptions = page.getByRole("listbox", { name: "Coding image" }).getByRole("option");
  const chosenImage = (await imageOptions.count()) > 1 ? imageOptions.nth(1) : imageOptions.first();
  const chosenImageLabel = (await chosenImage.innerText()).trim();
  await chosenImage.click();
  await sheet.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Environment saved", { exact: true })).toBeVisible();
  await expect(sheet).toBeHidden();

  await page.reload();
  await pickSelect(page, scope, projects[0].name);
  await expect(page.getByText("Python environment", { exact: true })).toBeVisible();
  await expect(page.getByText("PyPI, 1 host", { exact: true })).toBeVisible();
  await expect(page.getByText("1 set", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit environment", exact: true }).click();
  await expect(sheet.getByLabel("Name", { exact: true })).toHaveValue("Python environment");
  await expect(sheet.getByLabel("Environment variables", { exact: true })).toHaveValue("LOG_LEVEL=debug");
  await expect(sheet.getByLabel("Coding image", { exact: true })).toContainText(chosenImageLabel);

  // A secret for a host in the saved network access: write-only, listed by name and host.
  await sheet.getByRole("button", { name: "Add secret", exact: true }).click();
  const adding = page.getByRole("dialog", { name: "Add secret" });
  await adding.getByLabel("Variable name", { exact: true }).fill("api_token");
  await adding.getByLabel("Host", { exact: true }).fill("api.example.com");
  await adding.getByLabel("Value", { exact: true }).fill("e2e-secret-value");
  await adding.getByRole("button", { name: "Save secret", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Secret saved", { exact: true })).toBeVisible();
  await expect(sheet.getByRole("list", { name: "Secrets" })).toContainText("API_TOKEN");
  await expect(sheet.getByRole("list", { name: "Secrets" })).toContainText("api.example.com");
  const secrets = await (await page.request.get(`/v1/workspaces/${workspace.id}/projects/${projects[0].id}/coding/secrets`)).json();
  expect(secrets.map((s: { name: string }) => s.name)).toEqual(["API_TOKEN"]);
  expect(JSON.stringify(secrets)).not.toContain("e2e-secret-value");
  await sheet.getByRole("button", { name: "Close", exact: true }).click();

  // The other project's environment is its own.
  await pickSelect(page, scope, projects[1].name);
  await expect(page.getByText("Model API only", { exact: true })).toBeVisible();
  const other = await (await page.request.get(`/v1/workspaces/${workspace.id}/projects/${projects[1].id}/coding/environment`)).json();
  expect(other.enabled).toBe(false);
  expect(other.variables).toEqual({});
  const saved = await (await page.request.get(`/v1/workspaces/${workspace.id}/projects/${projects[0].id}/coding/environment`)).json();
  expect(saved.enabled).toBe(true);
  expect(saved.variables).toEqual({ LOG_LEVEL: "debug" });
  // Saving runs nothing.
  const runs = await page.request.get(`/v1/workspaces/${workspace.id}/projects/${projects[0].id}/coding/runs`);
  expect(runs.ok()).toBeTruthy();
  expect(await runs.json()).toEqual([]);
});
