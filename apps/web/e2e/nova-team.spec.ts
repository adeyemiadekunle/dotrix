import { expect, test } from "@playwright/test";

test("the fixed team is listed, and Juno opens in Chat without a side panel", async ({ page }) => {
  await page.goto("/w/dotrix");
  const agents = page.getByRole("complementary", { name: "Agents" });
  await expect(agents.locator(".ap-row")).toHaveCount(7);
  await expect(agents.getByText("Kai", { exact: true })).toHaveCount(1);
  await agents.getByRole("button", { name: /Juno Review/ }).click();
  await expect(page).toHaveURL(/\/chat\?new=1&agent=reviewer/);
  // Juno's reviews of Kai's turns are in a Codes session's Review view (work-panel.spec.ts); Chat has no side panel.
  await expect(page.locator(".side-panel")).toHaveCount(0);
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
