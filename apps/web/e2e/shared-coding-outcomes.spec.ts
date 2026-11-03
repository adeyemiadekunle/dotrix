import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("a shared task shows published PR evidence while coding sessions stay private", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const base = await page.evaluate(async () => {
    const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const [workspace] = await (await fetch("/v1/workspaces")).json();
    const project = await (
      await fetch(`/v1/workspaces/${workspace.id}/projects`, {
        method: "POST",
        headers,
        body: JSON.stringify({ key: "PUB", name: "Shared outcomes", source: "docs_only" }),
      })
    ).json();
    const root = `/v1/workspaces/${workspace.id}/projects/${project.id}`;
    const issue = await fetch(`${root}/issues`, { method: "POST", headers, body: JSON.stringify({ title: "Shared implementation", status: "review" }) });
    if (!issue.ok) throw new Error(`issue: ${issue.status}`);
    return root;
  });
  let state: "open" | "merged" | "closed" | null = "open";
  let ci: "passed" | null = "passed";
  await page.route("**/coding/issues/PUB-1/outcomes", (route) =>
    route.fulfill({
      json: [
        {
          pr_number: 17,
          pr_url: "https://github.com/acme/app/pull/17",
          pr_state: state,
          commit_sha: "a".repeat(40),
          turn: 1,
          finished_at: new Date().toISOString(),
          ci_state: ci,
          review_url: "https://github.com/acme/app/pull/17#pullrequestreview-1",
          ci_review_url: null,
          session_id: null,
        },
      ],
    }),
  );
  const openTask = async () => {
    await page.goto(`/w/${slug}/p/PUB/board`);
    await page.getByText("Shared implementation", { exact: true }).click();
    await expect(page.getByRole("region", { name: "Published coding outcomes", exact: true })).toBeVisible();
  };
  await openTask();
  const panel = page.getByRole("region", { name: "Published coding outcomes", exact: true });
  await expect(panel).toContainText("Open for review");
  await expect(panel).toContainText("CI for this commit: passed");
  await expect(panel.getByRole("link", { name: "Juno review on GitHub", exact: true })).toHaveAttribute("href", /pullrequestreview-1/);
  await expect(panel.getByRole("button", { name: "Open your coding session", exact: true })).toHaveCount(0);
  state = "merged";
  await openTask();
  await expect(panel).toContainText("The PR was merged on GitHub");
  const status = await page.evaluate(async (root) => (await (await fetch(`${root}/issues/PUB-1`)).json()).status, base);
  expect(status).toBe("review");
  state = "closed";
  await openTask();
  await expect(panel).toContainText("Closed without merging");
  state = null;
  ci = null;
  await openTask();
  await expect(panel).toContainText("PR state unconfirmed");
  await expect(panel).toContainText("CI for this commit: not confirmed");
});
