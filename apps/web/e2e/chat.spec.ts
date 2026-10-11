import { expect, test, type Page } from "@playwright/test";

import { signUp } from "./helpers";

// Chat on the API: conversations in a project and across projects, and the Code tab's sessions.
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

test("the agents answer, and a change waits for approval before it happens", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM");

  const box = page.getByLabel("Message");
  await box.fill("What's open?");
  await box.press("Enter");
  await expect(page).toHaveURL(/thread=.*project=KUM/);
  await expect(page.getByText("Test model reply: What's open?")).toBeVisible();
  const conversations = page.getByRole("navigation", { name: "Conversations" });
  await expect(conversations.getByText("What's open", { exact: true })).toBeVisible();

  // A new conversation for the change: it waits, and nothing happens until it's approved.
  await conversations.getByRole("button", { name: "New chat in Kumove" }).click();
  await expect(page).not.toHaveURL(/thread=/);
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
    await expect(page.getByText("Add dark mode")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
});

test("the agent picked answers, and the conversation keeps it", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page, "?project=KUM");

  const agent = page.getByLabel("Agent", { exact: true });
  await agent.selectOption("research");
  const name = ((await agent.locator("option:checked").textContent()) ?? "").split(" · ")[0]!;
  await page.getByLabel("Message").fill("Who else ships multi-zone?");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText("Test model reply: Who else ships multi-zone?")).toBeVisible();
  await expect(page.locator(".chat-msg.agent .who b").last()).toHaveText(name);
  await expect(page.getByLabel("Agent", { exact: true })).toHaveValue("research");
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
  await expect(page.getByText("Test model reply: How are both projects doing?")).toBeVisible();
  await expect(page.getByText(/In all projects the agents only read/)).toBeVisible();
  await expect(conversations.getByRole("button", { name: /How are both projects doing/ })).toContainText(/ALP|KUM/);
});

test("Chat's Code tab lists coding sessions, and switching back to Chat keeps the conversations", async ({ page }) => {
  await signUp(page);
  await addProject(page, "Kumove", "KUM");
  await openChat(page);
  await page.getByRole("tab", { name: "Code" }).click();
  await expect(page).toHaveURL(/tab=coding/);
  await expect(page.getByText("No coding sessions", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Start a coding session" })).toBeVisible();
  await page.getByRole("tab", { name: "Chat" }).click();
  await expect(page).not.toHaveURL(/tab=coding/);
  await expect(page.getByLabel("Message")).toBeVisible();
});
