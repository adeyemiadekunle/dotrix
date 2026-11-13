import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("an empty repository gives a prerequisite and a fresh check unlocks an editable Plan starter", async ({ page }) => {
  await signUp(page);
  await page.goto("/onboarding?mode=project&intent=new");
  await page.getByLabel("Project name", { exact: true }).fill("Private first app");
  await page.getByLabel("Project key", { exact: true }).fill("FIRST");
  await page.getByLabel("Project goal", { exact: true }).fill("Private consultant booking goal");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Connect GitHub", exact: true })).toBeVisible();
  const saved = new URL(page.url());
  const response = await page.evaluate(
    async ({ workspace, project }) => {
      const res = await fetch(`/v1/workspaces/${workspace}/projects/${project}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-Requested-With": "e2e" },
        body: JSON.stringify({ repo_url: "https://github.com/acme/first" }),
      });
      return res.status;
    },
    { workspace: saved.searchParams.get("workspace"), project: saved.searchParams.get("project") },
  );
  expect(response).toBe(200);
  let state: "empty" | "ready" | "unavailable" = "empty";
  let checks = 0;
  await page.route("**/repository/readiness", (route) => {
    checks++;
    return state === "unavailable"
      ? route.fulfill({ status: 503, json: { detail: "GitHub temporarily unavailable" } })
      : route.fulfill({
          json: {
            ready: state === "ready",
            full_name: "acme/first",
            default_branch: "main",
            commit_sha: state === "ready" ? "a".repeat(40) : null,
            reason: state === "ready" ? null : "Create an initial commit (for example, a README) on main, then check again before starting Kai.",
          },
        });
  });
  const agentCalls: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/agent/runs")) agentCalls.push(request.url());
  });
  saved.searchParams.set("step", "ready");
  await page.goto(saved.href);
  const check = page.getByRole("button", { name: "Check repository", exact: true });
  await expect(check).toBeVisible();
  expect(checks).toBe(0); // Saved readiness never makes a live GitHub check implicitly.
  await check.click();
  await expect(page.getByRole("region", { name: "Repository readiness" })).toContainText("Create an initial commit");
  await expect(page.getByRole("link", { name: "Plan first implementation", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open project", exact: true })).toBeVisible();
  state = "ready";
  await page.getByRole("button", { name: "Check repository again", exact: true }).click();
  await expect(page.getByRole("region", { name: "Repository readiness" })).toContainText("aaaaaaa");
  await expect(page.getByRole("link", { name: "Plan first implementation", exact: true })).toBeVisible();
  state = "unavailable";
  await page.getByRole("button", { name: "Check repository again", exact: true }).click();
  await expect(page.getByRole("region", { name: "Repository readiness" })).toContainText("GitHub temporarily unavailable");
  await expect(page.getByRole("link", { name: "Plan first implementation", exact: true })).toHaveCount(0);
  state = "ready";
  await page.getByRole("button", { name: "Check repository again", exact: true }).click();
  const starter = page.getByRole("link", { name: "Plan first implementation", exact: true });
  await expect(starter).toBeVisible();
  const href = await starter.getAttribute("href");
  expect(href).not.toContain("Private");
  expect(checks).toBe(4);
  await starter.click();
  await expect(page.getByRole("button", { name: "Mode: Plan", exact: true })).toBeVisible();
  await expect(page.getByLabel("Message", { exact: true })).toHaveText(/Plan the first useful implementation/);
  expect(agentCalls).toEqual([]);
});
