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

  // It's in the workspace queue too; approve it there.
  await page.getByRole("link", { name: "Notifications", exact: true }).click();
  await expect(page.getByText("“Create issue: Add dark mode”")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Send decision" }).click();
  await expect(page.getByText("Nothing waiting")).toBeVisible();

  // The run resumes in the background and creates the issue; the board shows it once it exists.
  await page.goto(page.url().replace("/approvals", `/p/${key}/board`));
  await expect(async () => {
    await page.reload();
    await expect(page.getByText("Add dark mode")).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });

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
