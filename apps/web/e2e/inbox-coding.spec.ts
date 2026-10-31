import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

// A turn of Kai's waiting on a person shows in the Inbox from the API (not the seeded store), with its
// decision: here changes that touch a file CI runs, held in Accept edits until someone accepts them.
test("the inbox accepts a coding turn's changes that wait because they change files CI runs", async ({ page }) => {
  await signUp(page);
  const key = "LINT";
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const project = await page.evaluate(
    async ([workspaceSlug, projectKey]) => {
      const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
      const workspaces = await (await fetch("/v1/workspaces", { headers })).json();
      const workspace = workspaces.find((w: { slug: string }) => w.slug === workspaceSlug);
      const created = await fetch(`/v1/workspaces/${workspace.id}/projects`, {
        method: "POST",
        headers,
        body: JSON.stringify({ key: projectKey, name: "Lint", source: "docs_only" }),
      });
      if (!created.ok) throw new Error(`Project creation failed: ${created.status}`);
      return created.json();
    },
    [slug, key],
  );
  const runId = "01a19000-0000-7000-8000-000000000001";
  const at = new Date().toISOString();
  await page.route("**/v1/workspaces/*/notifications**", (route) =>
    route.request().url().includes("/counts")
      ? route.fallback()
      : route.fulfill({
          json: [
            {
              id: "01a19000-0000-7000-8000-0000000000aa",
              kind: "approval",
              created_at: at,
              read: false,
              resolved: false,
              project_id: project.id,
              project_key: key,
              project_name: project.name,
              actor_user_id: null,
              actor_agent: "claude-code",
              title: `Changes ready for ${key}-1 (they change files CI runs): Lint`,
              count: 1,
              excerpt: null,
              issue_key: null,
              coding_run_id: runId,
            },
          ],
        }),
  );
  const run = {
    id: runId,
    project_id: project.id,
    issue_key: `${key}-1`,
    session_id: runId,
    turn: 1,
    status: "changes_ready",
    note: "Add a lint rule",
    files_changed: [
      { path: "src/lint.py", added: 1, removed: 0 },
      { path: "package.json", added: 1, removed: 1 },
    ],
    ci_sensitive: ["package.json"],
    can_decide: true,
    can_stop: true,
  };
  await page.route(`**/coding/runs/${runId}`, (route) => route.fulfill({ json: run }));
  const decided = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith(`/coding/runs/${runId}/decision`));
  await page.route(`**/coding/runs/${runId}/decision`, (route) => route.fulfill({ json: { ...run, status: "queued" } }));

  await page.goto(`/w/${slug}/inbox?n=01a19000-0000-7000-8000-0000000000aa`);
  const card = page.getByRole("group", { name: "Coding turn" });
  await expect(card).toContainText(`${key}-1 · turn 1`);
  await expect(card).toContainText("package.json");
  await expect(card.getByRole("note")).toContainText("They change files CI runs (package.json)");
  await card.getByRole("button", { name: "Accept and push" }).click();
  expect((await decided).postDataJSON()).toEqual({ decision: "approve", reason: null });
});
