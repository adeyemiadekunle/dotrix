import { expect, test } from "@playwright/test";

import { NOT_WIRED, signUpWithProject } from "./helpers";

test.fixme(true, NOT_WIRED);

// The e2e backend's web is canned (DOTRIX_SEARCH_PROVIDER=fake): every search finds one gov.uk
// page about VAT. "Research: <question>" makes the rule-based model search, read that page, and
// record a report with one claim quoted from it and one that isn't on it.

test("research a question: claims checked against the page, sources, and a saved note", async ({ page }) => {
  await signUpWithProject(page);
  await page.getByRole("link", { name: "Chat", exact: true }).click();
  await page.getByRole("button", { name: "Choose the agent and model" }).click();
  await page.getByRole("menuitemradio", { name: /Research agent/ }).click();
  const box = page.getByLabel("Message Research agent");
  await box.fill("Research: UK VAT rate");
  await box.press("Enter");

  await expect(page.getByText("Research done: the findings and their sources are below.")).toBeVisible();
  const report = page.getByRole("region", { name: "Research findings" });
  // The quoted claim is backed by a primary source read in full; the other isn't on the page.
  await expect(report.getByText("Supported", { exact: true })).toBeVisible();
  const assumptions = report.getByRole("region", { name: "Assumptions" });
  await expect(assumptions.getByText("It changes every month")).toBeVisible();
  await expect(assumptions.getByText("No quote found", { exact: true })).toBeVisible();

  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources.getByRole("link", { name: /VAT rates/ })).toHaveAttribute("href", "https://www.gov.uk/vat-rates");
  await expect(sources.getByText("gov.uk · read in full")).toBeVisible();
  await expect(sources.getByText("Primary", { exact: true })).toBeVisible();

  await report.getByRole("button", { name: "Save as research note" }).click();
  const saved = report.getByRole("link", { name: /Saved to research\/.*-research-uk-vat-rate\.md/ });
  await expect(saved).toBeVisible();
  await saved.click();
  await expect(page).toHaveURL(/knowledge\?file=research/);
  await expect(page.getByText("## Sources").or(page.getByRole("heading", { name: "Sources" })).first()).toBeVisible();
});
