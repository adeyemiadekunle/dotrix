import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("project cloud profiles persist without running scripts and stay separate", async ({ page }) => {
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
  await scope.selectOption(projects[0].id);
  const imageSelect = page.getByLabel("Environment coding image", { exact: true });
  const image = (await imageSelect.locator("option").count()) > 1 ? await imageSelect.locator("option").nth(1).getAttribute("value") : "";
  await imageSelect.selectOption(image ?? "");
  await page.getByRole("switch", { name: "Use cloud environment", exact: true }).click();
  await page.getByLabel("Environment name", { exact: true }).fill("Python environment");
  await page.getByLabel("Environment setup script", { exact: true }).fill("python3 --version");
  await page.getByLabel("Environment verification command", { exact: true }).fill("python3 -B -m unittest");
  await page.getByRole("button", { name: "Save environment", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Cloud environment saved", { exact: true })).toBeVisible();
  await page.reload();
  await scope.selectOption(projects[0].id);
  await expect(page.getByLabel("Environment name", { exact: true })).toHaveValue("Python environment");
  await expect(imageSelect).toHaveValue(image ?? "");
  await expect(page.getByRole("switch", { name: "Use cloud environment", exact: true })).toBeChecked();
  await scope.selectOption(projects[1].id);
  await expect(page.getByRole("switch", { name: "Use cloud environment", exact: true })).not.toBeChecked();
  const runs = await page.request.get(`/v1/workspaces/${workspace.id}/projects/${projects[0].id}/coding/runs`);
  expect(runs.ok()).toBeTruthy();
  expect(await runs.json()).toEqual([]);
});
