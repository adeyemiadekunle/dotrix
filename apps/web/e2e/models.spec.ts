import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

test("project agent models and per-run limits can be saved and reset", async ({ page }) => {
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  await page.evaluate(async (workspaceSlug) => {
    const headers = { "Content-Type": "application/json", "X-Requested-With": "e2e" };
    const workspaces = await (await fetch("/v1/workspaces", { headers })).json();
    const workspace = workspaces.find((w: { slug: string }) => w.slug === workspaceSlug);
    const response = await fetch(`/v1/workspaces/${workspace.id}/projects`, {
      method: "POST",
      headers,
      body: JSON.stringify({ key: "ROUTE", name: "Model routing", source: "docs_only" }),
    });
    if (!response.ok) throw new Error(`Project creation failed: ${response.status}`);
  }, slug);
  await page.goto(`/w/${slug}/p/ROUTE/overview`);
  await page.getByRole("button", { name: "Project settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Project settings" });
  await expect(dialog.getByLabel("Project model", { exact: true })).toHaveValue("e2e:rules");
  await expect(dialog.getByLabel("Automatic model routing", { exact: true })).not.toBeChecked();
  await dialog.getByLabel("Automatic model routing", { exact: true }).check();
  await dialog.getByLabel("Specialist model").fill("openai:cheap-model");
  await dialog.getByLabel("Default token limit per agent run").fill("10000");
  const saved = page.waitForResponse((r) => r.url().includes("/projects/") && r.request().method() === "PATCH");
  await dialog.getByRole("button", { name: "Save agent models" }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByText("Agent model settings saved")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Project settings", exact: true }).click();
  await expect(dialog.getByLabel("Automatic model routing", { exact: true })).toBeChecked();
  await expect(dialog.getByLabel("Specialist model")).toHaveValue("openai:cheap-model");
  await expect(dialog.getByLabel("Default token limit per agent run")).toHaveValue("10000");
  await dialog.getByLabel("Specialist model").fill("openai:other-model");
  await dialog.getByLabel("Specialist model").press("Enter");
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: "Project settings", exact: true }).click();
  await expect(dialog.getByLabel("Specialist model")).toHaveValue("openai:other-model");
  await dialog.getByLabel("Specialist model").fill("unsupported-model");
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog.getByRole("alert")).toContainText(/provider/i);
  await dialog.getByLabel("Automatic model routing", { exact: true }).uncheck();
  await dialog.getByLabel("Specialist model").fill("");
  await dialog.getByLabel("Default token limit per agent run").fill("");
  const reset = page.waitForResponse((r) => r.url().includes("/projects/") && r.request().method() === "PATCH");
  await dialog.getByRole("button", { name: "Save agent models" }).click();
  expect((await reset).status()).toBe(200);
  await expect(dialog.getByLabel("Automatic model routing", { exact: true })).not.toBeChecked();
  await expect(dialog.getByLabel("Specialist model")).toHaveValue("");
  await expect(dialog.getByLabel("Default token limit per agent run")).toHaveValue("");
});

test("a missing provider blocks the workspace until an encrypted personal key is connected", async ({ page }) => {
  let ready = false;
  await page.route("**/model-access", (route) =>
    route.fulfill({
      json: {
        ready,
        providers: ready ? ["xai"] : [],
        models: ready ? ["xai:grok-4.7"] : [],
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

test("every user connects a personal key without shared-key controls", async ({ page }) => {
  await page.route("**/model-access", (route) =>
    route.fulfill({
      json: { ready: false, providers: [], models: [], can_store_keys: true },
    }),
  );
  await signUp(page);
  await expect(page.getByLabel("Model API key")).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(page.getByText("Connect a workspace key for everyone")).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("saving a personal key in Settings refreshes the mounted setup gate", async ({ page }) => {
  let ready = false;
  let accessChecks = 0;
  await page.route("**/model-access", (route) => {
    accessChecks += 1;
    return route.fulfill({
      json: {
        ready,
        providers: ready ? ["openai"] : [],
        models: ready ? ["openai:gpt-5.5"] : [],
        can_store_keys: true,
      },
    });
  });
  await page.route("**/me/model-keys/openai", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    const response = await route.fetch();
    if (response.ok()) ready = true;
    await route.fulfill({ response });
  });
  await signUp(page);
  await expect(page.getByRole("heading", { name: "Connect a model to continue" })).toBeVisible();
  await page.getByRole("button", { name: "Model settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/my-models$/);
  const openai = page.locator(".srow-wrap").filter({ has: page.getByText("OpenAI", { exact: true }) });
  await openai.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByLabel("OpenAI API key", { exact: true }).fill("test-personal-provider-key-only");
  const beforeSave = accessChecks;
  await openai.getByRole("button", { name: "Save key", exact: true }).click();
  await expect(page.getByText("Your OpenAI key is saved", { exact: true })).toBeVisible();
  // Client navigation keeps ModelGate mounted: no reload or focus event can rescue a stale query.
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "Home", exact: true }).click();
  await expect.poll(() => accessChecks).toBeGreaterThan(beforeSave);
  await expect(page.getByRole("heading", { name: "Connect a model to continue" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main", exact: true })).toBeVisible();
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
  await page.goto(`/w/${slug}/coding?new=1&issue=${issueKey}`);
  await page.getByRole("button", { name: "Coding tool: Codex", exact: true }).click();
  await page.getByRole("option", { name: "OpenCode", exact: true }).click();
  await expect(page.getByRole("button", { name: "Coding model: grok-4.7", exact: true })).toBeVisible();
  const sent = page.waitForRequest((r) => r.method() === "POST" && /\/coding\/issues\/[^/]+\/runs$/.test(r.url()));
  await page.getByRole("button", { name: "Start coding", exact: true }).click();
  expect((await sent).postDataJSON()).toMatchObject({ agent: "opencode", model: "xai:grok-4.7", location: "cloud" });
});
