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

async function pickChatOption(page: Page, label: "Agent" | "Approvals" | "Mode", name: string | RegExp) {
  const picker = page.getByRole("button", { name: new RegExp(`^${label}:`) });
  await picker.click();
  const menu = page.getByRole("listbox", { name: label, exact: true });
  const option = menu.getByRole("option", { name, exact: true });
  const selected = (await option.innerText()).trim();
  await option.click();
  await expect(picker).toHaveAccessibleName(`${label}: ${selected}`);
  await expect(menu).toBeHidden();
  return selected;
}

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

  await expect(page.getByText("Nova · Lead adviser")).toBeVisible();
  await expect(page.getByRole("button", { name: "Remove request to involve Vega" })).toBeVisible();
  await page.getByLabel("Message").fill("Who else ships multi-zone?");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText(/Who else ships multi-zone/).last()).toBeVisible();
  await expect(page.locator(".chat-msg.agent .who b").last()).toHaveText("Nova");
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
  await expect(card.getByText("Refunds", { exact: true })).toBeVisible();
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

test("one list for conversations and coding sessions: a new session starts from it, and New chat goes back", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page);
  await expect(page.getByRole("tab", { name: "Code" })).toHaveCount(0); // no separate Code tab
  await page.getByRole("button", { name: "New coding session" }).click();
  await expect(page).toHaveURL(/tab=coding/);
  await expect(page.getByRole("heading", { name: "Start a coding session" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Conversations" })).toBeVisible(); // the same list beside it
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await expect(page).not.toHaveURL(/tab=coding/);
  await expect(page.getByLabel("Message")).toBeVisible();
});
