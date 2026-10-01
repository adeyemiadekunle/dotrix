import { expect, test } from "@playwright/test";

import { signUpWithProject } from "./helpers";

// The rule-based model: "Plan: a; b" stops at a checkpoint with those steps; anything else is
// echoed back ("Test model reply: …").

test("change the plan at a checkpoint, and the agent carries on with it", async ({ page }) => {
  await signUpWithProject(page);
  await page.getByRole("link", { name: "Chat", exact: true }).click();
  const box = page.getByLabel("Message the agents");
  await box.fill("Plan: Write the spec; Assess the impact");
  await box.press("Enter");

  const card = page.getByText("The plan, before going on").locator("..").locator("..");
  await expect(card.getByText("Assess the impact")).toBeVisible();
  await card.getByRole("button", { name: "Change the plan" }).click();
  await card.getByLabel("What to change in the plan").fill("Skip the impact");
  await card.getByRole("button", { name: "Continue with changes" }).click();

  // The agent carries on with the change (the rule-based model says what it heard).
  await expect(page.getByText(/The person wants changes to your plan: Skip the impact/)).toBeVisible();
  await expect(page.getByText("Changed the plan")).toBeVisible();
});

test("ask the Reviewer to review an issue, and triage a report", async ({ page }) => {
  const { key } = await signUpWithProject(page);
  await page.getByRole("button", { name: "New issue" }).click();
  await page.getByLabel("Title").fill("Retry failed uploads");
  await page.getByRole("button", { name: "Create issue" }).click();
  await expect(page).toHaveURL(new RegExp(`issue=${key}-1`));

  await page.getByRole("dialog").getByRole("button", { name: "Review", exact: true }).click();
  // The review opens in the chat panel, answered by the Reviewer.
  await expect(page.getByText(new RegExp(`Test model reply: Review ${key}-1 \\(Retry failed uploads`))).toBeVisible();
  await expect(page.getByText("Reviewer agent").first()).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Triage", exact: true }).click();
  await page.getByLabel("Report", { exact: true }).fill("Drivers see the wrong zone after switching depots");
  await page.getByRole("dialog").getByRole("button", { name: "Triage", exact: true }).click();
  await expect(page.getByText(/Test model reply: Triage this report/)).toBeVisible();
});
