import { expect, test } from "@playwright/test";

test("the fixed team opens Juno's keyboard-accessible review panel", async ({ page }) => {
  await page.goto("/w/dotrix");
  const agents = page.getByRole("complementary", { name: "Agents" });
  await expect(agents.locator(".ap-row")).toHaveCount(7);
  await expect(agents.getByText("Kai", { exact: true })).toHaveCount(1);
  await agents.getByRole("button", { name: /Juno Review/ }).click();
  const review = page.getByRole("complementary", { name: "Juno's review" });
  await expect(review).toBeVisible();
  await expect(page.getByText("Nova · Lead adviser")).toBeVisible();
  await review.getByRole("tab", { name: "Findings" }).click();
  await review.getByRole("tab", { name: "Findings" }).press("ArrowRight");
  await expect(review.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true");
  await page.reload();
  await expect(page.getByRole("complementary", { name: "Juno's review" })).toBeVisible();
});

test("Kai's instructions stay protected and additional guidance is editable", async ({ page }) => {
  await page.goto("/w/dotrix/settings/agents");
  await expect(page.getByText("7 built-in agents · Nova leads the team")).toBeVisible();
  await page.getByRole("button", { name: /Kai Coding/ }).click();
  await expect(page.getByLabel("Built-in instructions")).toHaveAttribute("readonly", "");
  await page.getByLabel("Additional instructions").fill("Explain the changes clearly.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Customised", { exact: true })).toBeVisible();
});

test("the review panel fits a small screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/w/dotrix/chat?new=1&agent=reviewer&panel=review");
  const review = page.getByRole("complementary", { name: "Juno's review" });
  await expect(review).toBeVisible();
  await expect(review.getByRole("tab", { name: "Findings" })).toBeVisible();
  await review.getByRole("button", { name: "Close the review panel" }).click();
  await expect(review).toHaveCount(0);
});
