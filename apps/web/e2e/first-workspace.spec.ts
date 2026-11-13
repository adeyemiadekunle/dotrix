import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("skipping the first step keeps Personal even after choosing to set up for a team", async ({ page }) => {
  await signUp(page);
  await page.goto("/onboarding");
  await expect(page.getByLabel("Organisation name", { exact: true })).toHaveCount(0);
  const progress = page.getByRole("list", { name: "Onboarding progress", exact: true });
  await expect(progress.locator('[aria-current="step"]')).toHaveText(/Profile/);
  await page.getByRole("button", { name: "Setting up for a team?", exact: true }).click();
  await expect(page.getByLabel("Organisation name", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How do you want to start?", exact: true })).toBeVisible();
  await expect(progress.locator('[aria-current="step"]')).toHaveText(/Starting point/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "How do you want to start?", exact: true })).toBeVisible();
  const state = await page.evaluate(async () => ({ user: await (await fetch("/v1/me")).json(), workspaces: await (await fetch("/v1/workspaces")).json() }));
  expect(state.workspaces).toHaveLength(1);
  expect(state.workspaces[0].kind).toBe("personal");
  expect(state.user.onboarding_workspace_id).toBe(state.workspaces[0].id);
});

test("an organisation save recovers a lost response and the stepper preserves its workspace", async ({ page }) => {
  await signUp(page);
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Setting up for a team?", exact: true }).click();
  await page.getByLabel("Organisation name", { exact: true }).fill("First delivery team");
  let calls = 0;
  await page.route("**/me/onboarding-workspace", async (route) => {
    calls++;
    const saved = await route.fetch();
    expect(saved.status()).toBe(200);
    await route.abort("failed");
  });
  await page.getByLabel("Organisation name", { exact: true }).press("Enter");
  await expect(page.getByRole("heading", { name: "How do you want to start?", exact: true })).toBeVisible();
  const selected = new URL(page.url()).searchParams.get("workspace");
  expect(selected).toBeTruthy();
  const state = await page.evaluate(async () => ({ user: await (await fetch("/v1/me")).json(), workspaces: await (await fetch("/v1/workspaces")).json() }));
  expect(state.workspaces).toHaveLength(2);
  expect(state.workspaces.find((w: { id: string }) => w.id === selected)).toMatchObject({ name: "First delivery team", kind: "organization", role: "owner" });
  expect(state.workspaces.some((w: { kind: string }) => w.kind === "personal")).toBeTruthy();
  expect(state.user.onboarding_workspace_id).toBe(selected);
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your workspace is saved", exact: true })).toBeVisible();
  await expect(page.getByText(/First delivery team · Organisation/)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your workspace is saved", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("radio", { name: "Explore an idea", exact: true }).check();
  await expect(page.getByRole("list", { name: "Onboarding progress", exact: true })).not.toContainText("GitHub");
  expect(calls).toBe(1);
});

test("workspace settings offers separate organisation creation and no conversion", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  await page.goto(`/w/${slug}/settings/workspace`);
  await expect(page.getByRole("button", { name: "Turn into an organisation", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Create organisation workspace", exact: true })).toHaveAttribute("href", "/onboarding?mode=project&team=1");
});

test("a saved organisation choice still allows personal setup after role restrictions", async ({ page }) => {
  await signUp(page);
  const chosen = await page.request.post("/v1/me/onboarding-workspace", {
    headers: { "X-Requested-With": "e2e" },
    data: { kind: "organization", name: "Earlier team" },
  });
  expect(chosen.status()).toBe(200);
  const organisation = await chosen.json();
  await page.route("**/v1/workspaces", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const rows = await response.json();
    return route.fulfill({
      json: rows.map((workspace: { id: string }) =>
        workspace.id === organisation.id ? { ...workspace, role: "member", permissions: ["workspace:view", "agents:chat", "issues:write"] } : workspace,
      ),
    });
  });
  await page.goto("/onboarding");
  await expect(page.getByRole("heading", { name: "Open your team workspace", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Set up a project in your own workspace", exact: true }).click();
  await expect(page.getByRole("heading", { name: "How do you want to start?", exact: true })).toBeVisible();
  await expect(page.getByLabel("Workspace", { exact: true })).not.toHaveValue(organisation.id);
});

test("a different saved choice opens its summary instead of continuing in the stale workspace", async ({ page }) => {
  await signUp(page);
  await page.goto("/onboarding");
  await page.route(
    "**/me/onboarding-workspace",
    async (route) => {
      const saved = await page.request.post("/v1/me/onboarding-workspace", {
        headers: { "X-Requested-With": "e2e" },
        data: { kind: "organization", name: "Saved in another tab" },
      });
      expect(saved.status()).toBe(200);
      return route.fulfill({ status: 409, json: { detail: "Your first workspace is already selected" } });
    },
    { times: 1 },
  );
  await page.getByRole("button", { name: "Skip", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your workspace is saved", exact: true })).toBeVisible();
  await expect(page.getByText(/Saved in another tab · Organisation/)).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Review it before continuing");
  await expect(page.getByLabel("Project name", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const selected = new URL(page.url()).searchParams.get("workspace");
  await expect(page.getByLabel("Workspace", { exact: true })).toHaveValue(selected!);
});

test("a background profile refetch reconciles another tab's saved organisation before project setup", async ({ page }) => {
  await signUp(page);
  await page.clock.install();
  await page.goto("/onboarding");
  await expect(page.getByRole("heading", { name: "Set up your profile", exact: true })).toBeVisible();
  const response = await page.request.post("/v1/me/onboarding-workspace", {
    headers: { "X-Requested-With": "e2e" },
    data: { kind: "organization", name: "Chosen from another tab" },
  });
  expect(response.status()).toBe(200);
  const organisation = await response.json();
  await page.clock.fastForward(31_000);
  const refreshed = page.waitForResponse((response) => response.request().method() === "GET" && response.url().endsWith("/v1/me"));
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    window.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    window.dispatchEvent(new Event("visibilitychange"));
  });
  await refreshed;
  await expect(page.getByRole("heading", { name: "Your workspace is saved", exact: true })).toBeVisible();
  await expect(page.getByText(/Chosen from another tab · Organisation/)).toBeVisible();
  await expect(page.getByLabel("Project name", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Workspace", { exact: true })).toHaveValue(organisation.id);
  expect(new URL(page.url()).searchParams.get("workspace")).toBe(organisation.id);
});
