import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("GitHub import requires reviewed selections and retains retry identity after a lost response", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const base = await page.evaluate(async () => {
    const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const [ws] = await (await fetch("/v1/workspaces")).json();
    const project = await (
      await fetch(`/v1/workspaces/${ws.id}/projects`, {
        method: "POST",
        headers,
        body: JSON.stringify({ key: "IMP", name: "Import project", source: "docs_only" }),
      })
    ).json();
    const root = `/v1/workspaces/${ws.id}/projects/${project.id}`;
    await fetch(`${root}/issues`, { method: "POST", headers, body: JSON.stringify({ title: "Existing human task" }) });
    return root;
  });
  const item = {
    source_id: 1001,
    number: 1,
    source_url: "https://github.com/acme/app/issues/1",
    title: "Imported scope",
    description: "Scope and acceptance criteria",
    status: "backlog",
    labels: ["backend"],
    assignee_user_id: null,
    assignee_name: null,
    github_assignees: ["unknown"],
    warnings: ["Unmapped GitHub assignee; left unassigned"],
    existing_key: null,
    blocked: false,
  };
  let revision = 1;
  await page.route("**/repository/issues/preview", (route) =>
    route.fulfill({
      json: {
        id: `11111111-1111-4111-8111-${String(revision++).padStart(12, "0")}`,
        repository: "acme/app",
        page: 1,
        has_more: true,
        skipped_pull_requests: 1,
        expires_at: new Date(Date.now() + 1800000).toISOString(),
        items: [
          item,
          { ...item, source_id: 1002, number: 2, existing_key: "IMP-1" },
          { ...item, source_id: 1003, number: 3, blocked: true, warnings: ["Closed without completion; excluded"] },
        ],
      },
    }),
  );
  const requests: unknown[] = [];
  let imported = false;
  await page.route("**/repository/issues/import", async (route) => {
    requests.push(route.request().postDataJSON());
    if (!imported) {
      const r = await page.request.post(`${base}/issues`, {
        headers: { "X-Requested-With": "e2e" },
        data: { title: "Imported scope", description: item.description, status: "backlog" },
      });
      expect(r.status()).toBe(201);
      imported = true;
      return route.abort("failed");
    }
    return route.fulfill({ json: { items: [{ source_id: 1001, issue_key: "IMP-2", outcome: "created" }] } });
  });
  await page.goto(`/w/${slug}/p/IMP/board`);
  await page.getByRole("button", { name: "Import from GitHub", exact: true }).click();
  const panel = page.getByRole("region", { name: "GitHub backlog import", exact: true });
  await expect(panel).toContainText("one-time import");
  await panel.getByRole("button", { name: "Load preview", exact: true }).click();
  await expect(panel).toContainText("Unmapped GitHub assignee");
  await expect(panel.getByRole("checkbox", { name: "Select GitHub issue 2", exact: true })).toBeDisabled();
  await expect(panel.getByRole("checkbox", { name: "Select GitHub issue 3", exact: true })).toBeDisabled();
  await panel.getByRole("checkbox", { name: "Select GitHub issue 1", exact: true }).check();
  const confirm = panel.getByRole("button", { name: "Import 1 selected issues", exact: true });
  await expect(confirm).toBeDisabled();
  await panel.getByRole("checkbox", { name: /I reviewed the selected content/ }).check();
  await confirm.click();
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(panel.getByRole("checkbox", { name: "Select GitHub issue 1", exact: true })).toBeChecked();
  await confirm.click();
  await expect(panel.getByRole("status")).toContainText("1 created");
  expect(requests).toHaveLength(2);
  expect(requests[0]).toEqual(requests[1]);
  await panel.getByRole("button", { name: "Back to board", exact: true }).click();
  await expect(page.getByText("Imported scope", { exact: true })).toHaveCount(1);
});
