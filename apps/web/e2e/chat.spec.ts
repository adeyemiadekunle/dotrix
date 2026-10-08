import { expect, test } from "@playwright/test";

import { signUpWithProject } from "./helpers";

// The e2e backend runs the agents on a rule-based model: "Create issue: <title>" asks to create
// that task (which waits for approval); anything else is echoed back.

test("the agents answer, and a change waits for approval before it happens", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  await page.getByRole("link", { name: "Chat", exact: true }).click();

  const box = page.getByLabel("Message the agents");
  // On screen even while the verify-email banner takes its line at the top.
  await expect(page.getByText(/Confirm your email address/)).toBeVisible();
  await expect(box).toBeInViewport();
  await box.fill("What's open?");
  await box.press("Enter");
  await expect(page.getByText("Test model reply: What's open?")).toBeVisible();

  // A new conversation for the change.
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  // Wait for the new conversation: opening it resets the message box.
  await expect(page).not.toHaveURL(/thread=/);
  await expect(page.getByRole("button", { name: "What changed since yesterday?" })).toBeVisible();
  await box.fill("Create issue: Add dark mode");
  await box.press("Enter");
  await expect(page.getByText("1 change waits for your approval")).toBeVisible();
  await expect(page.getByText("Create issue", { exact: true })).toBeVisible();

  // Nothing on the board yet.
  await page.goto(page.url().replace(/\/chat\?.*$/, `/p/${key}/board`));
  await expect(page.getByText("Add dark mode")).toHaveCount(0);

  // It's in Notifications too (the bell has a dot until it's decided); approve it there.
  await expect(page.getByRole("link", { name: "Open notifications (1 waiting)" })).toBeVisible();
  await page.getByRole("link", { name: "Notifications", exact: true }).click();
  const list = page.getByRole("navigation", { name: "Notifications" });
  await list.getByRole("button", { name: /Project manager wants to make a change/ }).click();
  await expect(page.getByText("“Create issue: Add dark mode”")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Send decision" }).click();
  await expect(page.getByText("Decided. Nothing is waiting from this request now.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open notifications", exact: true })).toBeVisible();

  // The run resumes in the background and creates the issue; the board shows it once it exists.
  await page.goto(page.url().replace(/\/approvals.*$/, `/p/${key}/board`));
  await expect(async () => {
    await page.reload();
    await expect(page.getByText("Add dark mode")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });

  // Home shows what the agents did: the issue they created, not the people's own work.
  await page.getByRole("link", { name: "Home", exact: true }).click();
  const agentWork = page.locator("section").filter({ has: page.getByRole("heading", { name: "Agent activity" }) });
  await expect(agentWork.getByRole("link", { name: /Add dark mode/ })).toBeVisible();

  // The conversations are titled from their first message (no model call).
  await page.getByRole("link", { name: "Chat", exact: true }).click();
  const conversations = page.getByRole("navigation", { name: "Conversations" });
  await expect(conversations.getByText("What's open", { exact: true })).toBeVisible();
  await expect(conversations.getByText("Create issue: Add dark mode", { exact: true })).toBeVisible();

  // Rename one from the title above the conversation.
  await conversations.getByText("Create issue: Add dark mode", { exact: true }).click();
  await page.getByRole("button", { name: "Rename conversation" }).click();
  const title = page.getByLabel("Conversation title");
  await title.fill("Dark mode request");
  await title.press("Enter");
  await expect(conversations.getByText("Dark mode request")).toBeVisible();
});

test("pick who answers with the + menu or @", async ({ page }) => {
  await signUpWithProject(page);
  await page.getByRole("link", { name: "Chat", exact: true }).click();

  await page.getByRole("button", { name: "Choose the agent and model" }).click();
  await page.getByRole("menuitemradio", { name: /Research agent/ }).click();
  const box = page.getByLabel("Message Research agent");
  await box.fill("Who else ships multi-zone?");
  await box.press("Enter");
  await expect(page.getByText("Test model reply: Who else ships multi-zone?")).toBeVisible();
  await expect(page.getByText("Research agent", { exact: true }).last()).toBeVisible(); // the reply's label

  // The conversation keeps the agent; "@product " switches it.
  await box.fill("@product ");
  await expect(page.getByLabel("Message Product agent")).toBeVisible();
  await page.getByLabel("Message Product agent").fill("And the stories?");
  await page.getByLabel("Message Product agent").press("Enter");
  await expect(page.getByText("Test model reply: And the stories?")).toBeVisible();

  // Back to Auto by removing the chip.
  await page.getByRole("button", { name: "Product agent: back to auto" }).click();
  await expect(page.getByLabel("Message the agents")).toBeVisible();
});

test("an owner creates an agent, and it answers in the chat when picked", async ({ page }) => {
  await signUpWithProject(page);
  const projectUrl = page.url().replace(/\/board.*$/, "");
  // Agents live in Settings (owners and admins).
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: "Agents", exact: true }).click();
  await expect(page.getByText("@research")).toBeVisible();
  await page.getByRole("link", { name: "New agent" }).click();
  await page.getByLabel("Handle").fill("security");
  await page.getByLabel("Name", { exact: true }).fill("Security reviewer");
  await page.getByLabel("Description").fill("Reviews changes for security risks.");
  await page.getByLabel("Instructions").fill("Look for leaked secrets and unsafe defaults.");
  await page.getByRole("button", { name: "Create agent" }).click();
  await expect(page).toHaveURL(/\/settings\/agents\/security$/);
  await page.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: "Agents", exact: true }).click();
  // The list, not the agent's own page (or Next's route announcer) while it navigates.
  await expect(page).toHaveURL(/\/settings\/agents$/);
  await expect(page.getByRole("main").getByText("@security")).toBeVisible();

  // "@security" at the start of a message picks it; its reply is labelled with its name.
  await page.goto(`${projectUrl}/chat`);
  const box = page.getByLabel("Message the agents");
  await box.fill("@security Any leaks?");
  await expect(page.getByLabel("Message Security reviewer")).toBeVisible();
  await page.getByLabel("Message Security reviewer").press("Enter");
  await expect(page.getByText("Test model reply: Any leaks?")).toBeVisible();
  await expect(page.getByText("Security reviewer", { exact: true }).first()).toBeVisible();
});

test("ask across projects: the agents read every project picked, and the conversation is listed apart", async ({
  page,
}) => {
  await signUpWithProject(page, "Kumove", "KUM");
  await page.getByRole("link", { name: "New project" }).first().click();
  await page.getByText("Documents only", { exact: true }).click();
  await page.getByLabel("Name").fill("Alpha");
  await page.getByLabel("Key").fill("ALP");
  await page.getByRole("button", { name: "Create project", exact: true }).click();
  await expect(page).toHaveURL(/\/p\/ALP\/overview/);

  await page.getByRole("link", { name: "Chat", exact: true }).click();
  await page.getByRole("button", { name: "New chat across projects" }).click();
  await expect(page).toHaveURL(/across=1/);
  const about = page.getByRole("group", { name: "About" });
  await expect(about.getByRole("checkbox")).toHaveCount(2);
  const box = page.getByLabel("Message the agents");
  await box.fill("How are both projects doing?");
  await box.press("Enter");
  await expect(page.getByText("Test model reply: How are both projects doing?")).toBeVisible();
  await expect(page.getByText(/Read-only: changes are made in a project's own conversation/)).toBeVisible();
  const conversations = page.getByRole("navigation", { name: "Conversations" });
  await expect(conversations.getByRole("button", { name: /How are both projects doing/ })).toContainText(/ALP|KUM/);
});

test("Chat's Code tab lists coding sessions, and switching back to Chat keeps the conversations", async ({ page }) => {
  await signUpWithProject(page);
  await page.getByRole("link", { name: "Chat", exact: true }).click();
  await page.getByRole("tab", { name: "Code" }).click();
  await expect(page).toHaveURL(/tab=coding/);
  await expect(page.getByText("No coding sessions yet.")).toBeVisible();
  await expect(page.getByText("Coding sessions", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Chat" }).click();
  await expect(page).not.toHaveURL(/tab=coding/);
  await expect(page.getByLabel("Message the agents")).toBeVisible();
});
