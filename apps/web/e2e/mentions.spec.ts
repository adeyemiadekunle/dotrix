import { expect, test } from "@playwright/test";

import { createOrganisation, createTask, currentWorkspace, newUser, signUp } from "./helpers";

// An @mention in a task's comment, in a real organisation: the person named finds it in their Inbox.

test("@mention a colleague in a comment, and they find it in their Inbox", async ({ page, browser }) => {
  await signUp(page, newUser("Ada Tester"));
  await createOrganisation(page, "Mention Ltd");
  const workspace = await currentWorkspace(page);
  const headers = { "X-Requested-With": "e2e" };
  const created = await page.request.post(`/v1/workspaces/${workspace.id}/projects`, { headers, data: { key: "KUM", name: "Kumove", source: "docs_only" } });
  expect(created.status()).toBe(201);
  const project = await created.json();
  await createTask(page, workspace.id, project.id, { title: "Fix the upload retries" });

  // Bob joins by the workspace's invite link.
  const invite = await page.request.post(`/v1/workspaces/${workspace.id}/invites/links`, { headers, data: {} });
  expect(invite.status()).toBe(201);
  const link = new URL((await invite.json()).url);
  const other = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const bob = await other.newPage();
  await signUp(bob, newUser("Bob Builder"));
  await bob.goto(link.pathname + link.search);
  await bob.getByRole("button", { name: "Accept and join" }).click();
  await expect(bob).toHaveURL(new RegExp(`/w/${workspace.slug}`));

  // Ada comments on the task and picks Bob from the @ list.
  await page.goto(`/w/${workspace.slug}/p/KUM/board`);
  await page.getByRole("button", { name: "Fix the upload retries" }).click();
  const drawer = page.getByRole("dialog", { name: "Task: Fix the upload retries" });
  const comment = drawer.getByRole("textbox", { name: "Comment" });
  await comment.pressSequentially("Can you take this, @bo");
  await drawer.locator(".pop .mi", { hasText: "Bob Builder" }).click();
  await expect(comment).toHaveValue("Can you take this, @Bob Builder ");
  await comment.pressSequentially("please?");
  await comment.press("ControlOrMeta+Enter");
  await expect(drawer.getByText("Can you take this, @Bob Builder please?")).toBeVisible();

  // Bob sees it in his Inbox, under Mentions, and it opens the task.
  await bob.goto(`/w/${workspace.slug}/inbox`);
  await bob.getByRole("tab", { name: /Mentions/ }).click();
  await expect(bob.getByText(/Ada Tester/).first()).toBeVisible();
  await expect(bob.getByText(/Fix the upload retries/).first()).toBeVisible();
  await other.close();
});
