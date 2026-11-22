import { expect, test, type Page } from "@playwright/test";

import { signUp } from "./helpers";

// A project's Knowledge → Coverage: what the connected repository's knowledge covers. Without a
// connected repository (the e2e server has no GitHub App) it says how to get the first inventory.

const slugOf = (page: Page) => new URL(page.url()).pathname.split("/")[2]!;

async function addProject(page: Page, name: string, key: string) {
  await page.evaluate(
    async ({ slug, name, key }) => {
      const h = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
      const ws = (await (await fetch("/v1/workspaces", { headers: h })).json()) as { id: string; slug: string }[];
      const w = ws.find((x) => x.slug === slug)!;
      const r = await fetch(`/v1/workspaces/${w.id}/projects`, {
        method: "POST",
        headers: h,
        body: JSON.stringify({ key, name, source: "docs_only", description: "", access: "workspace" }),
      });
      if (!r.ok) throw new Error(`project: ${r.status}`);
    },
    { slug: slugOf(page), name, key },
  );
}

test("Knowledge shows the repository's coverage, and how to get the first inventory", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await page.goto(`/w/${slugOf(page)}/p/KUM/knowledge`);
  await page.getByRole("tab", { name: "Coverage" }).click();
  await expect(page).toHaveURL(/view=coverage/);
  await expect(page.getByText("No inventory yet")).toBeVisible();
  await expect(page.getByText(/Connect the project's GitHub repository \(project settings/)).toBeVisible();
  // Taking one without a connected repository says why it can't.
  await page.getByRole("button", { name: "Take inventory now" }).click();
  await expect(page.getByText(/Connect the project's GitHub repository first|Reading code isn't set up/)).toBeVisible();
});
