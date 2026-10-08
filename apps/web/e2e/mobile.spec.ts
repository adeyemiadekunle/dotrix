import { devices, expect, test } from "@playwright/test";

import { NOT_WIRED, signUpWithProject } from "./helpers";

test.fixme(true, NOT_WIRED);

// A phone: the sidebar is a sheet, the board's columns stack, and the chat input stays on screen.
test.use({ ...devices["Pixel 7"], viewport: { width: 390, height: 844 } });

test("on a phone the board stacks its columns and chat keeps its input on screen", async ({ page }) => {
  const { key } = await signUpWithProject(page);

  // Stacked columns, with Done folded away until it's opened.
  await expect(page.getByRole("button", { name: "Hide To do" })).toBeVisible();
  await page.getByRole("button", { name: "Show Done" }).click();
  await expect(page.getByRole("button", { name: "Hide Done" })).toBeVisible();

  // "Ask in Chat" opens the workspace's Chat about this project; its input sits inside the screen.
  await page.getByRole("link", { name: "Ask in Chat" }).click();
  await expect(page).toHaveURL(new RegExp(`/chat\\?project=${key}`));
  const box = page.getByLabel("Message the agents");
  await expect(box).toBeInViewport();
  await box.fill("What's open?");
  await box.press("Enter");
  await expect(page.getByText("Test model reply: What's open?")).toBeVisible();
  await expect(box).toBeInViewport();

  // The sidebar opens as a sheet from the header's toggle.
  await page.getByRole("button", { name: "Toggle Sidebar" }).first().click();
  await expect(page.getByRole("link", { name: "Notifications", exact: true })).toBeVisible();
});
