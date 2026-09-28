import { expect, test } from "@playwright/test";

import { signUpWithProject } from "./helpers";

// The e2e backend runs the agents on a rule-based model: "Create issue: <title>" asks to create
// that task (which waits for approval); anything else is echoed back.

test("the PM answers, and a change waits for approval before it happens", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  await page.getByRole("link", { name: "Chat", exact: true }).click();

  const box = page.getByLabel("Message the project manager");
  await box.fill("What's open?");
  await box.press("Enter");
  await expect(page.getByText("Test model reply: What's open?")).toBeVisible();

  // A new conversation for the change.
  await page.getByRole("button", { name: "New conversation" }).first().click();
  await box.fill("Create issue: Add dark mode");
  await box.press("Enter");
  await expect(page.getByText("1 change waits for your approval")).toBeVisible();
  await expect(page.getByText("Create issue", { exact: true })).toBeVisible();

  // Nothing on the board yet.
  await page.goto(`${page.url().split("/chat")[0]}/board`);
  await expect(page.getByText("Add dark mode")).toHaveCount(0);

  // It's in the workspace queue too; approve it there.
  await page.getByRole("link", { name: "Approvals" }).click();
  await expect(page.getByText("“Create issue: Add dark mode”")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Send decision" }).click();
  await expect(page.getByText("Nothing waiting")).toBeVisible();

  // The run resumed and the issue exists.
  await page.goto(page.url().replace("/approvals", `/p/${key}/board`));
  await expect(page.getByText("Add dark mode")).toBeVisible();

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
