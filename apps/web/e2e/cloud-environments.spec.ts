import { expect, test } from "@playwright/test";
import { pickSelect, signUp } from "./helpers";

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
  await pickSelect(page, scope, projects[0].name);
  const imageSelect = page.getByLabel("Environment coding image", { exact: true });
  await imageSelect.click();
  const imageOptions = page.getByRole("listbox", { name: "Environment coding image" }).getByRole("option");
  const chosenImage = (await imageOptions.count()) > 1 ? imageOptions.nth(1) : imageOptions.first();
  const chosenImageLabel = (await chosenImage.innerText()).trim();
  await chosenImage.click();
  await page.getByRole("switch", { name: "Use cloud environment", exact: true }).click();
  await page.getByLabel("Environment name", { exact: true }).fill("Python environment");
  await page.getByLabel("Environment setup script", { exact: true }).fill("python3 --version");
  await page.getByLabel("Environment verification command", { exact: true }).fill("python3 -B -m unittest");
  await page.getByRole("button", { name: "Save environment", exact: true }).click();
  await expect(page.getByRole("region", { name: "Notifications" }).getByText("Cloud environment saved", { exact: true })).toBeVisible();
  await page.reload();
  await pickSelect(page, scope, projects[0].name);
  await expect(page.getByLabel("Environment name", { exact: true })).toHaveValue("Python environment");
  await expect(imageSelect).toContainText(chosenImageLabel);
  await expect(page.getByRole("switch", { name: "Use cloud environment", exact: true })).toBeChecked();
  await pickSelect(page, scope, projects[1].name);
  await expect(page.getByRole("switch", { name: "Use cloud environment", exact: true })).not.toBeChecked();
  const runs = await page.request.get(`/v1/workspaces/${workspace.id}/projects/${projects[0].id}/coding/runs`);
  expect(runs.ok()).toBeTruthy();
  expect(await runs.json()).toEqual([]);
});
