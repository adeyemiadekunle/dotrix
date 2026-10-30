import { expect, test, type Page } from "@playwright/test";

import { signUp } from "./helpers";

// Chat on the API: conversations in a project and across projects, and Kai's coding sessions in the same list.
// The e2e backend runs the agents on a rule-based model: "Create issue: <title>" asks to create
// that issue (which waits for approval); anything else is echoed back.

const slugOf = (page: Page) => new URL(page.url()).pathname.split("/")[2]!;

/** A docs-only project, made through the API. */
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

async function openChat(page: Page, search = "") {
  await page.goto(`/w/${slugOf(page)}/chat${search}`);
  await expect(page.locator("#main-content h1").first()).toContainText(/Good|Chat/);
}

async function pickChatOption(page: Page, label: "Approvals" | "Mode", name: string | RegExp) {
  const picker = page.getByRole("button", { name: new RegExp(`^${label}:`) });
  await picker.click();
  // Approvals keeps its own list; Mode is a section of the + menu (projects + modes).
  const menu = label === "Approvals" ? page.getByRole("listbox", { name: "Approvals", exact: true }) : page.locator(".pop[role='listbox']");
  const option = menu.getByRole("option", { name, exact: true });
  const selected = (await option.innerText()).trim();
  await option.click();
  await expect(picker).toHaveAccessibleName(`${label}: ${selected}`);
  await expect(menu).toBeHidden();
  return selected;
}

test("fx works in every mode", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await page.route("**/v1/workspaces/*/projects/*/agent/runtime-options", (route) => route.fulfill({ json: { fx_available: true, fx_providers: ["openai"] } }));
  await page.route("**/v1/workspaces/*/models", (route) =>
    route.fulfill({
      json: [
        { id: "anthropic:test", provider: "anthropic", name: "Anthropic test", source: "personal" },
        { id: "openai:test", provider: "openai", name: "OpenAI test", source: "personal" },
      ],
    }),
  );
  await openChat(page, "?project=KUM");
  await expect(page.getByRole("button", { name: "Chat runtime: Standard" })).toBeVisible();
  await pickChatOption(page, "Mode", "Plan");
  await page.getByRole("button", { name: "Chat runtime: Standard" }).click();
  await page.getByRole("option", { name: "fx", exact: true }).click();
  await expect(page.getByRole("button", { name: "Mode: Plan" })).toBeVisible(); // the mode you picked stays
  await expect(page.getByRole("button", { name: "Model: OpenAI test" })).toBeVisible();
  await expect(page.getByText(/Nova runs on fx, in every mode/)).toBeVisible();
  await expect(page.getByText(/can't involve specialists here/)).toHaveCount(0);
  await pickChatOption(page, "Mode", "Build");
  await page.route("**/v1/workspaces/*/projects/*/agent/runs", (route) => route.fulfill({ status: 422, json: { detail: "Test only" } }));
  const submitted = page.waitForRequest((request) => request.method() === "POST" && request.url().endsWith("/agent/runs"));
  await page.getByLabel("Message").fill("What is in the project?");
  await page.getByLabel("Message").press("Enter");
  const body = (await submitted).postDataJSON();
  expect(body).toMatchObject({ chat_runtime: "fx", model: "openai:test", work_mode: "build", agent: "auto" });
});

test("the agents answer, and a change waits for approval before it happens", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM");

  const box = page.getByLabel("Message");
  await box.fill("What's open?");
  await box.press("Enter");
  await expect(page).toHaveURL(/thread=.*project=KUM/);
  await expect(page.getByText("Test model reply: What's open?")).toBeVisible({ timeout: 30_000 });
  // What the agents did stays with the reply (kept after the run), folded until asked for.
  await page.getByRole("button", { name: "Steps" }).first().click();
  await expect(page.getByRole("list", { name: "Steps" })).toBeVisible();
  const conversations = page.getByRole("navigation", { name: "Conversations" });
  await expect(conversations.getByText("What's open", { exact: true })).toBeVisible();

  // A new conversation for the change: it waits, and nothing happens until it's approved.
  await conversations.getByRole("button", { name: "New chat in Kumove" }).click();
  await expect(page).not.toHaveURL(/thread=/);
  await pickChatOption(page, "Approvals", "Manual"); // a personal workspace starts on Accept edits
  await page.getByLabel("Message").fill("Create issue: Add dark mode");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText("1 change waits for your approval")).toBeVisible();
  const change = page.locator(".change", { hasText: "Create issue" });
  await expect(change.getByText("Waiting for your decision")).toBeVisible();
  await change.getByRole("button", { name: "Approve" }).click();
  await expect(change.getByText("Approved", { exact: true })).toBeVisible();
  await expect(conversations.getByText("Create issue: Add dark mode", { exact: true })).toBeVisible();

  // The run resumes in the background and creates the issue; the board shows it once it exists.
  await expect(async () => {
    await page.goto(`/w/${slugOf(page)}/p/KUM/board`);
    await expect(page.getByRole("region", { name: "Backlog", exact: true })).toBeVisible();
    await expect(page.getByText("Add dark mode")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
});

test("in Accept edits what you ask for goes through, approved by you", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM");
  await expect(page.getByRole("button", { name: /^Approvals:/ })).toHaveAccessibleName("Approvals: Accept edits"); // your own workspace's default
  await page.getByLabel("Message").fill("Create issue: Add search");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText(/Done\./)).toBeVisible();
  await expect(page.getByText("1 change waits for your approval")).toHaveCount(0);
  await expect(async () => {
    await page.goto(`/w/${slugOf(page)}/p/KUM/board`);
    await expect(page.getByRole("region", { name: "Backlog", exact: true })).toBeVisible();
    await expect(page.getByText("Add search")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
});

test("a specialist mention keeps Nova as the adviser", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM&agent=research");

  await expect(page.getByRole("button", { name: "Project and mode" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove request to involve Vega" })).toBeVisible();
  await page.getByLabel("Message").fill("Who else ships multi-zone?");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText(/Who else ships multi-zone/).last()).toBeVisible();
  await expect(page.locator(".chat-msg.agent .who b").last()).toHaveText("Nova");
});

test("the + menu opens and cancels without touching the draft", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM");

  const box = page.getByLabel("Message");
  const plus = page.getByRole("button", { name: "Project and mode" });
  const menu = page.locator(".pop[role='listbox']");

  await plus.click();
  await expect(menu).toBeVisible();
  // Clicking where the pill is cancels (the veil catches it) and an empty box stays empty.
  const r = (await plus.boundingBox())!;
  await page.mouse.click(r.x + r.width / 2, r.y + r.height / 2);
  await expect(menu).toBeHidden();
  await expect(box).toHaveValue("");

  await box.fill("Ship it");
  await plus.click();
  await page.mouse.click(20, 20); // a click away cancels, and the draft is untouched
  await expect(menu).toBeHidden();
  await expect(box).toHaveValue("Ship it");

  // A typed @ still opens the same list, and a pick removes the trigger.
  await box.fill("Ship it @");
  await expect(menu).toBeVisible();
  await menu.getByRole("option", { name: "Plan", exact: true }).click();
  await expect(box).toHaveValue("Ship it ");
  await expect(page.getByRole("button", { name: "Mode: Plan" })).toBeVisible();
});

test("one conversation moves from Discuss to Plan to Build, and the plan is kept to build from", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM");

  const mode = page.getByRole("button", { name: /^Mode:/ });
  await expect(mode).toHaveAccessibleName("Mode: Discuss"); // a new conversation starts by talking it through
  await page.getByLabel("Message").fill("How would refunds work?");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText("Test model reply: How would refunds work?")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".chat-msg.user .badge").last()).toHaveText("Discuss");

  await pickChatOption(page, "Mode", "Plan");
  await page.getByLabel("Message").fill("Save plan: Refunds; Add refund(); Test it");
  await page.getByLabel("Message").press("Enter");
  const card = page.getByRole("group", { name: "Plan version 1" });
  await expect(card.getByText("Refunds", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(card.getByText("Test it")).toBeVisible();
  await expect(card.getByText("after 1")).toBeVisible();
  await expect(page.getByText("Saved the plan; switch to Build to carry it out.")).toBeVisible();

  // Building from the plan says which version, in Build mode; the conversation then stays in Build.
  await card.getByRole("button", { name: "Build this plan" }).click();
  await expect(page.getByText("Test model reply: Build plan version 1: Refunds")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".chat-msg.user .badge").last()).toHaveText("Build");
  await expect(mode).toHaveAccessibleName("Mode: Build");
});

test("ask across projects: the conversation reads only and is listed apart, with its projects", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await addProject(page, "Alpha", "ALP");
  await openChat(page);

  const conversations = page.getByRole("navigation", { name: "Conversations" });
  await conversations.getByRole("button", { name: "New chat in Conversations" }).click();
  await expect(page).toHaveURL(/across=1/);
  const projects = page.getByRole("group", { name: "Projects" });
  await expect(projects.getByRole("checkbox")).toHaveCount(2);
  await page.getByLabel("Message").fill("How are both projects doing?");
  await page.getByLabel("Message").press("Enter");
  await expect(page).toHaveURL(/thread=.*across=1/);
  await expect(page.getByText("Test model reply: How are both projects doing?")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/In all projects the agents only read/)).toBeVisible();
  await expect(conversations.getByRole("button", { name: /How are both projects doing/ })).toContainText(/ALP|KUM/);
});

test("Chat and Codes are separate pages, Codes right below Chat in the sidebar", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page);
  const side = page.getByRole("navigation", { name: "Main" });
  const items = await side.locator(".sitem").allInnerTexts();
  const chatAt = items.findIndex((t) => t.trim() === "Chat");
  expect(items[chatAt + 1]?.trim()).toBe("Codes");
  await expect(page.getByRole("navigation", { name: "Sessions" })).toHaveCount(0); // Chat lists conversations only
  await side.getByRole("button", { name: "Codes", exact: true }).click();
  await expect(page).toHaveURL(/\/codes$/);
  await expect(page.getByRole("heading", { name: "Start a session" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New session" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Sessions" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Conversations" })).toHaveCount(0);
  // An older link to a new coding session in Chat opens Codes.
  await page.goto(`/w/${slugOf(page)}/chat?tab=coding`);
  await expect(page).toHaveURL(/\/codes\?new=1$/);
  await expect(page.getByRole("heading", { name: "Start a session" })).toBeVisible();
  await page.goto(`/w/${slugOf(page)}/chat`);
  await expect(page.getByLabel("Message")).toBeVisible();
});

test("active project chat can queue, cancel, and steer without losing a failed draft", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM");
  await page.getByLabel("Message").fill("Check the project");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText("Test model reply: Check the project")).toBeVisible({ timeout: 30_000 });
  const location = page.url();
  let entries: Record<string, unknown>[] = [];
  let reject = false;
  await page.route("**/agent/runs?**", async (route) => {
    const response = await route.fetch();
    const runs = (await response.json()) as { id: string; status: string }[];
    await route.fulfill({ json: runs.map((run) => ({ ...run, status: "running", reply: null })) });
  });
  await page.route("**/agent/runs/*/stream", (route) =>
    route.fulfill({ contentType: "text/event-stream", body: 'event: activity\ndata: {"text":"Reading evidence"}\n\n' }),
  );
  await page.route("**/agent/threads/*/inputs**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") return route.fulfill({ json: entries });
    if (request.method() === "DELETE") {
      const id = request.url().split("/").at(-1);
      entries = entries.map((item) => (item.id === id ? { ...item, status: "cancelled" } : item));
      return route.fulfill({ json: entries.find((item) => item.id === id) });
    }
    if (reject) return route.fulfill({ status: 409, json: { detail: "The turn has just finished" } });
    const body = request.postDataJSON() as { message: string; kind: string; client_id: string };
    const item = {
      ...body,
      id: body.client_id,
      status: "pending",
      run_id: crypto.randomUUID(),
      delivered_run_id: null,
      error: null,
      created_at: new Date().toISOString(),
    };
    entries = [item, ...entries];
    return route.fulfill({ status: 202, json: item });
  });
  try {
    await page.goto(location);
    await expect(page.getByLabel("Delivery action")).toHaveValue("queue");
    const box = page.getByLabel("Message");
    await box.fill("Compare the alternatives afterward");
    await box.press("Enter");
    await expect(box).toHaveValue("");
    await expect(page.getByText("Queued follow-up: Compare the alternatives afterward")).toBeVisible();
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(page.getByText("Queued follow-up: Compare the alternatives afterward")).toBeHidden();
    await page.getByLabel("Delivery action").selectOption("steer");
    reject = true;
    await box.fill("Only consider self-hosted options");
    await box.press("Enter");
    await expect(page.getByText("The turn has just finished")).toBeVisible();
    await expect(box).toHaveValue("Only consider self-hosted options");
    reject = false;
    await expect(box).toBeEnabled();
    await box.press("Enter");
    await expect(page.getByText("Steering: Only consider self-hosted options")).toBeVisible();
    expect(entries[0]?.kind).toBe("steer");
  } finally {
    // Polling may leave a route.fetch response active when the assertions finish.
    await page.unrouteAll({ behavior: "wait" });
  }
});
