import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

// A personal workspace is one person's: every task is theirs, so the tasks page is "Tasks" and
// lists unassigned work too, and Home has no team to show.

test("in a personal workspace every task is yours: Tasks lists unassigned work and Home shows no team", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  await page.evaluate(async () => {
    const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const [ws] = await (await fetch("/v1/workspaces")).json();
    const project = await (
      await fetch(`/v1/workspaces/${ws.id}/projects`, {
        method: "POST",
        headers,
        body: JSON.stringify({ key: "SOLO", name: "Solo project", source: "docs_only" }),
      })
    ).json();
    // No assignee: as an agent or an import would leave it.
    await fetch(`/v1/workspaces/${ws.id}/projects/${project.id}/issues`, { method: "POST", headers, body: JSON.stringify({ title: "Unassigned groundwork" }) });
  });

  await page.goto(`/w/${slug}`);
  const nav = page.getByRole("navigation", { name: "Main", exact: true });
  await expect(nav.getByRole("button", { name: /^Tasks/ })).toBeVisible();
  await expect(nav.getByRole("button", { name: /^My Tasks/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Tasks", exact: true })).toBeVisible();
  await expect(page.getByRole("tabpanel").getByText("Unassigned groundwork")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Team" })).toHaveCount(0);
  await expect(page.getByText(/assigned to you/)).toHaveCount(0);

  await nav.getByRole("button", { name: /^Tasks/ }).click();
  await expect(page.locator("#main-content h1").first()).toHaveText("Tasks");
  await expect(page.getByText("Unassigned groundwork")).toBeVisible();

  // A project has no members to show, add or share with, and no lead to pick.
  await page.goto(`/w/${slug}/p/SOLO/overview`);
  await expect(page.locator("#main-content h1").first()).toHaveText("Solo project");
  for (const name of ["Members", "Add member", "Share"]) await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
  await expect(page.getByText("Lead", { exact: true })).toHaveCount(0);
  await page.goto(`/w/${slug}/projects`);
  await expect(page.getByRole("columnheader", { name: "Lead" })).toHaveCount(0);
});
