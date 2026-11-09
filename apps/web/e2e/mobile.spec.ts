import { devices, expect, test } from "@playwright/test";

import { createTask, signUpWithProject } from "./helpers";

// A phone: the sidebar is a sheet behind "Open navigation", and a task and Chat's message box
// stay on the screen.
test.use({ ...devices["Pixel 7"], viewport: { width: 390, height: 844 } });

test("on a phone the board, a task and Chat fit the screen, and the sidebar opens as a sheet", async ({ page }) => {
  const { workspace, project } = await signUpWithProject(page);
  await createTask(page, workspace.id, project.id, { title: "Draft the pricing page" });
  await page.reload();

  // Nothing is wider than the phone.
  const card = page.getByRole("region", { name: "To Do", exact: true }).getByRole("button", { name: "Draft the pricing page" });
  await expect(card).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await card.click();
  const drawer = page.getByRole("dialog", { name: "Task: Draft the pricing page" });
  await expect(drawer.getByRole("textbox", { name: "Task title" })).toBeInViewport();
  const size = await drawer.boundingBox();
  expect(size!.x).toBeGreaterThanOrEqual(0);
  expect(size!.x + size!.width).toBeLessThanOrEqual(390);
  await drawer.getByRole("button", { name: "Close" }).click();
  await expect(drawer).toBeHidden();

  // The sidebar is a sheet: opened from the top bar, it takes you to Chat and closes.
  const nav = page.getByRole("navigation", { name: "Main", exact: true });
  await expect(nav.getByRole("button", { name: "Chat", exact: true })).not.toBeInViewport();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(nav.getByRole("button", { name: "Chat", exact: true })).toBeInViewport();
  await nav.getByRole("button", { name: "Chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chat/);
  await expect(nav.getByRole("button", { name: "Chat", exact: true })).not.toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
