import { expect, test } from "@playwright/test";

// Table folded into List, on seeded data: List's columns can be hidden, and old Table links open List.

test("List's columns can be hidden, and an old Table link opens List", async ({ page }) => {
  await page.goto("/w/dotrix/p/WEB/table");
  const head = page.locator(".tlist .thead");
  await expect(head.getByText("Labels")).toBeVisible();
  await page.getByRole("button", { name: "Columns" }).click();
  await page.locator(".pop").getByText("Labels").click();
  await page.keyboard.press("Escape");
  await expect(head.getByText("Labels")).toHaveCount(0);
  await expect(head.getByText("Priority")).toBeVisible();
});
