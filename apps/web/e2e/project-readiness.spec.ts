import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("saved readiness agrees across onboarding, overview and an empty board without starting agents", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const { workspaceId, projectId } = await page.evaluate(async () => {
    const [ws] = await (await fetch("/v1/workspaces")).json();
    const response = await fetch(`/v1/workspaces/${ws.id}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "e2e" },
      body: JSON.stringify({ key: "READY", name: "A working idea", source: "docs_only", description: "Help solo developers organise a new idea." }),
    });
    if (!response.ok) throw new Error(await response.text());
    return { workspaceId: ws.id, projectId: (await response.json()).id };
  });
  const panel = page.getByRole("region", { name: "Project readiness", exact: true });
  for (const path of [
    `/w/${slug}/p/READY/overview`,
    `/w/${slug}/p/READY/board`,
    `/onboarding?${new URLSearchParams({ workspace: workspaceId, project: projectId, mode: "project", step: "ready" })}`,
  ]) {
    await page.goto(path);
    await expect(panel.getByRole("heading", { name: "Capture the first useful scope", exact: true })).toBeVisible();
    // The details are initially expanded on Overview/onboarding and collapsed on empty task views.
    if (!(await panel.getByText("Your model access (private)", { exact: true }).isVisible()))
      await panel.getByText("Readiness details", { exact: true }).click();
    await expect(panel).toContainText("GitHub is optional");
    await expect(panel).toContainText("no usable personal connection");
    await expect(panel).toContainText("Default agent guidance does not count");
    await expect(panel.getByRole("link", { name: "Open project tasks", exact: true })).toHaveAttribute("href", `/w/${slug}/p/READY/board`);
  }
  const runs = await page.request.get(`/v1/workspaces/${workspaceId}/projects/${projectId}/agent/runs`);
  expect(runs.ok()).toBeTruthy();
  expect(await runs.json()).toEqual([]);
});

test("sample readiness stays explicitly illustrative and performs no readiness requests", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (/\/projects\/[^/]+\/readiness/.test(request.url())) requests.push(request.url());
  });
  await page.goto("/w/dotrix/p/WEB/overview");
  const panel = page.getByRole("region", { name: "Project readiness", exact: true });
  await expect(panel).toContainText("Illustrative sample");
  await expect(panel.getByRole("button")).toHaveCount(0);
  expect(requests).toEqual([]);
});
