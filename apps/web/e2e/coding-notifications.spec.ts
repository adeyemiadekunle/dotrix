import { expect, test } from "@playwright/test";

const at = "2026-11-13T10:00:00Z";
const cases = [
  { name: "uses the notified session when another session has the same task", listed: true, linked: true, approval: false },
  { name: "loads the notified run when its session is absent from the list", listed: false, linked: true, approval: false },
  { name: "loads the notified run when the API has no session back-reference", listed: true, linked: false, approval: false },
  { name: "keeps changes-ready approval controls for the notified run", listed: true, linked: true, approval: true },
];

for (const scenario of cases) {
  test(`coding notification ${scenario.name}`, async ({ page, context, baseURL }) => {
    await context.addCookies([{ name: "dx_session", value: "1", url: baseURL! }]);
    const status = scenario.approval ? "changes_ready" : "failed";
    const older = {
      session_id: "older-session",
      project_id: "p1",
      project_key: "TEST",
      project_name: "Test project",
      issue_key: "TEST-1",
      issue_title: "Fix navigation",
      title: "Original session",
      agent: "codex",
      status,
      state: "idle",
      turns: 1,
      location: "cloud",
      started_at: at,
      updated_at: at,
      pinned: false,
      archived: false,
    };
    const newer = { ...older, session_id: "newer-session", title: "Newer session", status: "queued" };
    const run = {
      id: "original-run",
      session_id: older.session_id,
      project_id: "p1",
      issue_key: "TEST-1",
      turn: 1,
      agent: "codex",
      status,
      location: "cloud",
      note: "The original coding turn",
      summary: "Original result",
      files_changed: [],
      events: [],
      screenshots: [],
      ci_sensitive: [],
      can_decide: scenario.approval,
      created_at: at,
      updated_at: at,
    };
    await page.route("**/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown = [];
      if (path === "/v1/features") data = { organisations: true };
      else if (path === "/v1/me") data = { id: "u1", display_name: "Test User", email: "test@example.com" };
      else if (path === "/v1/workspaces") data = [{ id: "w1", slug: "test-workspace", name: "Test workspace", kind: "personal", permissions: ["agents:code"] }];
      else if (path.endsWith("/members"))
        data = [{ user_id: "u1", display_name: "Test User", email: "test@example.com", role: "owner", sees_all_projects: true, project_ids: [] }];
      else if (path.endsWith("/projects"))
        data = [{ id: "p1", key: "TEST", name: "Test project", status: "active", access: "open", created_at: at, updated_at: at }];
      else if (path.endsWith("/issues") || path.endsWith("/issues/TEST-1")) {
        const issue = {
          id: "i1",
          key: "TEST-1",
          project_id: "p1",
          title: "Fix navigation",
          type: "task",
          status: "todo",
          priority: "none",
          labels: [],
          checklist: [],
          due: null,
          description: "",
          created_at: at,
          updated_at: at,
        };
        data = path.endsWith("/issues") ? [issue] : issue;
      } else if (path.endsWith("/model-access")) data = { ready: true };
      else if (path.endsWith("/notifications/counts")) data = { unread: 1, by_kind: { coding: 1 } };
      else if (path.endsWith("/notifications"))
        data = [
          {
            id: "completion",
            kind: scenario.approval ? "approval" : "coding",
            project_id: "p1",
            project_key: "TEST",
            actor_agent: "codex",
            actor_user_id: null,
            title: "Kai's original turn",
            excerpt: "Original outcome",
            count: 1,
            issue_key: "TEST-1",
            coding_run_id: run.id,
            coding_session_id: scenario.linked ? older.session_id : null,
            run_id: null,
            thread_id: null,
            read: false,
            resolved: false,
            created_at: at,
          },
        ];
      else if (path.endsWith("/coding/sessions")) data = scenario.listed ? [newer, older] : [newer];
      else if (path.endsWith("/coding/runs/original-run")) data = run;
      else if (path.endsWith("/coding/sessions/older-session")) data = [run];
      await route.fulfill({ json: data });
    });

    await page.goto("/w/test-workspace/inbox?n=completion");
    if (scenario.approval) {
      const turn = page.getByRole("group", { name: "Coding turn" });
      await expect(turn.getByRole("button", { name: "Accept and push" })).toBeVisible();
      await expect(turn.getByRole("button", { name: "Discard" })).toBeVisible();
    } else if (!scenario.listed || !scenario.linked) {
      await expect(page.getByRole("group", { name: "Coding turn" })).toContainText("The original coding turn");
    }
    if (!scenario.approval) await expect(page.locator(".change-f .badge")).toHaveText(status.replaceAll("_", " "));
    await page.getByRole("button", { name: "Open the session", exact: true }).click();
    await expect(page).toHaveURL(/\/codes\?session=older-session$/);
  });
}
