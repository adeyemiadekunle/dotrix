import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

test("a missing provider blocks the workspace until an encrypted personal key is connected", async ({ page }) => {
  let ready = false;
  await page.route("**/model-keys/access", (route) =>
    route.fulfill({
      json: {
        ready,
        providers: ready ? ["xai"] : [],
        models: ready ? ["xai:grok-4.7"] : [],
        personal_keys_allowed: true,
        can_manage_keys: true,
        can_store_keys: true,
      },
    }),
  );
  await signUp(page);
  await expect(page.getByRole("heading", { name: "Connect a model to continue" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect and continue" })).toBeDisabled();
  await page.getByLabel("Model provider").selectOption("xai");
  const fakeKey = "test-provider-key-for-setup-only";
  await page.getByLabel("Model API key").fill(fakeKey);
  const saved = page.waitForResponse((r) => r.url().endsWith("/me/model-keys/xai") && r.request().method() === "PUT");
  // Only readiness is simulated: saving and encrypted-key metadata use the real API.
  ready = true;
  await page.getByRole("button", { name: "Connect and continue" }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Connect a model to continue" })).toHaveCount(0);
  await expect(page.getByLabel("Model API key")).toHaveCount(0);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  await page.goto(`/w/${slug}/settings/my-models`);
  await expect(page.getByText("xAI (Grok)", { exact: true })).toBeVisible();
  await expect(page.getByText(fakeKey, { exact: true })).toHaveCount(0);
  await page.getByLabel("Your default coding tool").selectOption("opencode");
  await expect(page.getByText("Default coding tool saved")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Your default coding tool")).toHaveValue("opencode");
});

test("an organisation that forbids personal keys explains who can connect a provider", async ({ page }) => {
  await page.route("**/model-keys/access", (route) =>
    route.fulfill({
      json: { ready: false, providers: [], models: [], personal_keys_allowed: false, can_manage_keys: false, can_store_keys: true },
    }),
  );
  await signUp(page);
  await expect(page.getByText("Your organisation uses its own keys.", { exact: false })).toBeVisible();
  await expect(page.getByLabel("Model API key")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Switch workspace" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("a new coding session offers compatible tools and sends the chosen OpenCode provider", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  const issueKey = await page.evaluate(async (slug) => {
    const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const workspaces = await (await fetch("/v1/workspaces")).json();
    const workspace = workspaces.find((w: { slug: string }) => w.slug === slug);
    const base = `/v1/workspaces/${workspace.id}/projects`;
    const project = await (
      await fetch(base, { method: "POST", headers, body: JSON.stringify({ key: "TOOLS", name: "Tool selection", source: "docs_only" }) })
    ).json();
    const issue = await (
      await fetch(`${base}/${project.id}/issues`, { method: "POST", headers, body: JSON.stringify({ type: "task", title: "Choose a coding tool" }) })
    ).json();
    if (!issue.key) throw new Error("The test issue was not created");
    return issue.key as string;
  }, slug);
  await page.route("**/projects/*/coding", (route) =>
    route.fulfill({
      json: {
        available: true,
        agent: "codex",
        default_tool: "codex",
        sandbox: "docker",
        reason: null,
        local_available: false,
        local_tools: [],
        tools: [
          { agent: "codex", available: true, models: [] },
          { agent: "claude-code", available: true, models: [] },
          { agent: "opencode", available: true, model: "xai:grok-4.7", models: ["xai:grok-4.7", "google_genai:gemini-3.8-flash"] },
        ],
      },
    }),
  );
  await page.route("**/coding/issues/*/runs", (route) => route.fulfill({ status: 409, json: { detail: "Test request captured" } }));
  await page.goto(`/w/${slug}/chat?tab=coding&issue=${issueKey}`);
  await page.getByRole("button", { name: "Coding tool: Codex", exact: true }).click();
  await page.getByRole("option", { name: "OpenCode", exact: true }).click();
  await expect(page.getByRole("button", { name: "Coding model: grok-4.7", exact: true })).toBeVisible();
  const sent = page.waitForRequest((r) => r.method() === "POST" && /\/coding\/issues\/[^/]+\/runs$/.test(r.url()));
  await page.getByRole("button", { name: "Start coding", exact: true }).click();
  expect((await sent).postDataJSON()).toMatchObject({ agent: "opencode", model: "xai:grok-4.7", location: "cloud" });
});
