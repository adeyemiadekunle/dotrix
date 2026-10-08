import { expect, test } from "@playwright/test";

import { NOT_WIRED, newUser, signUp, signUpWithProject } from "./helpers";

test.fixme(true, NOT_WIRED);

test("@mention a colleague in a comment, and they find it in Notifications", async ({ page, browser }) => {
  const { key } = await signUpWithProject(page);
  const board = page.url();
  // Turning it into an organisation keeps its address.
  const slug = /\/w\/([^/]+)/.exec(board)![1]!;

  // Turn the workspace into an organisation and invite Bob with a link.
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: "Invites" }).click();
  await page.getByLabel("Organisation name").fill("Mention Ltd");
  await page.getByRole("button", { name: "Turn into an organisation" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Turn into an organisation" }).click();
  await page.getByRole("button", { name: "Create link" }).click();
  const link = (await page.getByText(/\/invites\/accept\?token=/).textContent())!.trim();

  const other = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const bob = await other.newPage();
  await signUp(bob, newUser("Bob Builder"));
  await bob.goto(link.slice(link.indexOf("/invites/accept")));
  await bob.getByRole("button", { name: "Accept and join" }).click();
  await expect(bob).toHaveURL(new RegExp(`/w/${slug}$`));

  // Ada comments on an issue and picks Bob from the @ list.
  await page.goto(board);
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Fix the upload retries");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));
  const comment = page.getByLabel("Comment", { exact: true });
  await comment.pressSequentially("Can you take this, @bo");
  await expect(page.getByRole("listbox", { name: "Mention someone" }).getByRole("option", { name: /Bob Builder/ })).toBeVisible();
  await comment.press("Enter");
  await expect(comment).toHaveValue("Can you take this, @Bob Builder ");
  await comment.pressSequentially("?");
  await comment.press("ControlOrMeta+Enter");
  await expect(page.getByText("Can you take this, @Bob Builder ?")).toBeVisible();

  // Bob sees it under Mentions, with what was said and a way to the issue.
  await bob.getByRole("link", { name: "Notifications", exact: true }).click();
  await bob.getByRole("tab", { name: /Mentions/ }).click();
  await bob.getByRole("navigation", { name: "Notifications" }).getByRole("button", { name: new RegExp(`Ada Tester mentioned you on ${key}-1`) }).click();
  await expect(bob.getByRole("blockquote")).toHaveText("Can you take this, @Bob Builder ?");
  await bob.getByRole("link", { name: `Open ${key}-1` }).click();
  await expect(bob).toHaveURL(new RegExp(`/p/${key}/board\\?issue=${key}-1`));
  await other.close();
});
