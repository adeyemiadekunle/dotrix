import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("baseline reviews retain drafts, retry safely and require a fresh acknowledgement after evidence changes", async ({ page }) => {
  await signUp(page);
  const created = await page.evaluate(async () => {
    const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const [workspace] = await (await fetch("/v1/workspaces")).json();
    return (
      await fetch(`/v1/workspaces/${workspace.id}/projects`, {
        method: "POST",
        headers,
        body: JSON.stringify({ key: "BASE", name: "Existing app", source: "existing_repo", repo_url: "https://github.com/acme/app" }),
      })
    ).status;
  });
  expect(created).toBe(201);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const snapshot = {
    id: "11111111-1111-4111-8111-111111111111",
    repo_full_name: "acme/app",
    commit_sha: "a".repeat(40),
    policy_version: "test",
    path_count: 3,
    created_at: "2026-11-03T00:00:00Z",
  };
  await page.route("**/repository/knowledge", (route) =>
    route.fulfill({
      json: {
        snapshot,
        statuses: { analyzed: 1, pending: 1, excluded: 1 },
        inventory_complete: true,
        discovery_complete: false,
        domains: [{ domain: "architecture", title: "Architecture", status: "partial", paths: 2, analyzed: 1, excluded: 1, gap: null }],
      },
    }),
  );
  await page.route("**/repository/knowledge/pages", (route) =>
    route.fulfill({
      json: {
        commit_sha: snapshot.commit_sha,
        pages: [{ path: "docs/wiki/architecture.md", version: 1, updated_at: snapshot.created_at, citations: 1, stale: [] }],
      },
    }),
  );
  let digest = "a".repeat(64);
  let review: null | { id: string; digest: string; decision: string; notes: string; evidence: object; reviewed_by_id: null; created_at: string } = null;
  let humanContext: null | { revision: string; notes: string; updated_by_id: null; updated_at: string } = null;
  const state = () => ({
    digest,
    can_confirm: true,
    current: review?.decision === "confirmed" && review.digest === digest,
    blockers: [],
    evidence: { coverage: { snapshot } },
    review,
    human_context: humanContext,
  });
  await page.route("**/repository/knowledge/baseline", (route) => route.fulfill({ json: state() }));
  const requests: { request_id: string; digest: string; decision: string; notes: string }[] = [];
  await page.route("**/repository/knowledge/baseline/reviews", (route) => {
    const body = route.request().postDataJSON();
    requests.push(body);
    // An unconfirmed request can be retried with the same ID before it has saved anything.
    if (requests.length === 1) return route.abort("failed");
    if (body.notes.trim()) {
      digest = String.fromCharCode(97 + requests.length).repeat(64);
      humanContext = { revision: `context-${requests.length}`, notes: body.notes, updated_by_id: null, updated_at: snapshot.created_at };
    }
    review = {
      id: `review-${requests.length}`,
      digest,
      decision: body.decision,
      notes: body.notes,
      evidence: {},
      reviewed_by_id: null,
      created_at: snapshot.created_at,
    };
    return route.fulfill({ json: state() });
  });
  const modelCalls: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/agent/runs")) modelCalls.push(request.url());
  });
  await page.goto(`/w/${slug}/p/BASE/overview`);
  await page.getByRole("button", { name: "Review repository baseline", exact: true }).click();
  await expect(page).toHaveURL(/knowledge\?view=coverage/);
  const panel = page.getByRole("region", { name: "Repository baseline", exact: true });
  await expect(panel).toContainText("Not yet confirmed by a person");
  await expect(page.getByText("acme/app", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Not read 1", exact: true })).toBeVisible();
  const notes = panel.getByRole("textbox", { name: "Shared goals, constraints, corrections and open questions", exact: true });
  await notes.fill("Goal: bookings for consultants. Hosting remains unresolved.");
  const confirm = panel.getByRole("button", { name: "Confirm reviewed baseline", exact: true });
  await expect(confirm).toBeDisabled();
  await panel.getByRole("checkbox").check();
  await confirm.click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(notes).toHaveValue("Goal: bookings for consultants. Hosting remains unresolved.");
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(panel).toContainText("Reviewed scope — current evidence");
  expect(requests).toHaveLength(2);
  expect(requests[0]!.request_id).toBe(requests[1]!.request_id);
  await expect(panel.getByRole("button", { name: "Plan from reviewed baseline", exact: true })).toBeVisible();
  digest = "b".repeat(64);
  humanContext = {
    revision: "another-editor",
    notes: "Another editor clarified: only self-hosted authentication.",
    updated_by_id: null,
    updated_at: snapshot.created_at,
  };
  await panel.getByRole("button", { name: "Reload baseline", exact: true }).click();
  await expect(panel).toContainText("Evidence changed — review this baseline again");
  await expect(panel.getByRole("checkbox")).not.toBeChecked();
  await expect(confirm).toBeDisabled();
  await expect(panel.getByRole("button", { name: "Plan from reviewed baseline", exact: true })).toHaveCount(0);
  await expect(panel.getByText("Another editor clarified: only self-hosted authentication.", { exact: true })).toBeVisible();
  await notes.fill("");
  await panel.getByRole("checkbox").check();
  await confirm.click();
  await expect(panel).toContainText("Reviewed scope — current evidence");
  await expect(panel.getByText("Another editor clarified: only self-hosted authentication.", { exact: true })).toBeVisible();
  expect(requests[2]!.notes).toBe("");
  await notes.fill("Hosting needs a human decision before planning.");
  await panel.getByRole("button", { name: "Save corrections and context", exact: true }).click();
  await expect(panel).toContainText("Corrections requested — resolve them before planning");
  expect(requests[2]!.request_id).not.toBe(requests[1]!.request_id);
  expect(requests[3]!.request_id).not.toBe(requests[2]!.request_id);
  expect(modelCalls).toEqual([]);
});
