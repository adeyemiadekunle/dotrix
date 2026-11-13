import { expect, test, type Page } from "@playwright/test";

import { createTask, signUp } from "./helpers";

// What waits on you is decided where it's shown: a corner notice on Home and the agents panel
// approve or reject in place, the same decision the Inbox makes (here against stubbed coding turns).

async function project(page: Page, key: string) {
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const made = await page.evaluate(
    async ([workspaceSlug, projectKey]) => {
      const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
      const workspaces = await (await fetch("/v1/workspaces", { headers })).json();
      const workspace = workspaces.find((w: { slug: string }) => w.slug === workspaceSlug);
      const created = await fetch(`/v1/workspaces/${workspace.id}/projects`, {
        method: "POST",
        headers,
        body: JSON.stringify({ key: projectKey, name: projectKey, source: "docs_only" }),
      });
      if (!created.ok) throw new Error(`Project creation failed: ${created.status}`);
      return { workspace: workspace.id as string, ...(await created.json()) } as { workspace: string; id: string; name: string };
    },
    [slug, key],
  );
  return { slug, ...made };
}

const turn = (id: string, projectId: string, key: string, status: string) => ({
  id,
  project_id: projectId,
  issue_key: `${key}-1`,
  session_id: id,
  turn: 1,
  status,
  note: "Fix the login",
  files_changed: [],
  ci_sensitive: [],
  can_decide: true,
  can_stop: true,
  created_at: new Date().toISOString(),
});

test("a corner notice approves Kai's checked changes in place", async ({ page }) => {
  await signUp(page);
  const key = "NOTE";
  const p = await project(page, key);
  const runId = "01a19000-0000-7000-8000-000000000011";
  const at = new Date().toISOString();
  await page.route("**/v1/workspaces/*/notifications**", (route) =>
    route.request().url().includes("/counts")
      ? route.fallback()
      : route.fulfill({
          json: [
            {
              id: "01a19000-0000-7000-8000-0000000000bb",
              kind: "approval",
              created_at: at,
              read: false,
              resolved: false,
              project_id: p.id,
              project_key: key,
              project_name: p.name,
              actor_user_id: null,
              actor_agent: "claude-code",
              title: `Changes ready for ${key}-1`,
              count: 1,
              excerpt: null,
              issue_key: null,
              coding_run_id: runId,
            },
          ],
        }),
  );
  const run = turn(runId, p.id, key, "changes_ready");
  await page.route(`**/coding/runs/${runId}`, (route) => route.fulfill({ json: run }));
  const decided = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith(`/coding/runs/${runId}/decision`));
  await page.route(`**/coding/runs/${runId}/decision`, (route) => route.fulfill({ json: { ...run, status: "queued" } }));

  await page.goto(`/w/${p.slug}`);
  const notice = page.getByRole("region", { name: "Waiting for you" });
  await expect(notice).toContainText("needs your approval");
  await notice.getByRole("button", { name: "Approve" }).click();
  expect((await decided).postDataJSON()).toEqual({ decision: "approve", reason: null });
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(`Pushing Kai's changes on ${key}-1`)).toBeVisible();
});

test("the agents panel rejects a Kai session waiting to start, without opening it", async ({ page }) => {
  await signUp(page);
  const key = "PANE";
  const p = await project(page, key);
  // The issue the session codes, so the panel can name it.
  await createTask(page, p.workspace, p.id, { title: "Fix the login" });
  const sessionId = "01a19000-0000-7000-8000-000000000021";
  const runId = "01a19000-0000-7000-8000-000000000022";
  const at = new Date().toISOString();
  await page.route(`**/v1/workspaces/${p.workspace}/coding/sessions`, (route) =>
    route.fulfill({
      json: [
        {
          session_id: sessionId,
          project_id: p.id,
          project_key: key,
          project_name: p.name,
          issue_key: `${key}-1`,
          issue_title: "Fix the login",
          agent: "claude-code",
          status: "awaiting_approval",
          turns: 1,
          branch: null,
          pr_number: null,
          pr_url: null,
          pr_state: null,
          state: "idle",
          sandbox: "none",
          title: null,
          pinned: false,
          archived: false,
          thread_id: null,
          location: "cloud",
          started_at: at,
          updated_at: at,
        },
      ],
    }),
  );
  const run = turn(runId, p.id, key, "awaiting_approval");
  await page.route(`**/coding/sessions/${sessionId}`, (route) => route.fulfill({ json: [run] }));
  const decided = page.waitForRequest((r) => r.method() === "POST" && r.url().endsWith(`/coding/runs/${runId}/decision`));
  await page.route(`**/coding/runs/${runId}/decision`, (route) => route.fulfill({ json: { ...run, status: "rejected" } }));

  await page.goto(`/w/${p.slug}/projects`);
  await page.getByRole("button", { name: /^Agents/ }).click();
  const panel = page.getByRole("complementary", { name: "Agents" });
  await expect(panel).toContainText(`Waiting for approval to code ${key}-1`);
  await panel.getByRole("button", { name: "Reject", exact: true }).click();
  expect((await decided).postDataJSON()).toEqual({ decision: "reject", reason: null });
  await expect(page.getByRole("region", { name: "Notifications" }).getByText(`Rejected Kai's turn on ${key}-1`)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/w/${p.slug}/projects$`));
});
