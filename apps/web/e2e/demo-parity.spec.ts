import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

test("sample Chat and Codes use the shared lists and message presentation without API requests", async ({ page }) => {
  const errors: string[] = [];
  const apiCalls: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/v1/")) apiCalls.push(request.url());
  });
  await page.goto("/w/dotrix/chat");
  await page.locator(".chat-list .sitem").first().click();
  await expect(page.getByText("Sample conversation · Sign in to work with Nova.")).toBeVisible();
  await expect(page.locator(".chat-msg").first()).toBeVisible();
  await page.goto("/w/dotrix/codes");
  await page.getByRole("button", { name: /WEB-154 Fix broken anchor links/ }).click();
  await expect(page.getByText("Sample session · Sign in to work with Kai.")).toBeVisible();
  await expect(page.locator(".chat-msg").first()).toBeVisible();
  await page.getByRole("button", { name: "Changes", exact: true }).click();
  await expect(page.getByRole("table", { name: "Diff" })).toHaveCount(3);
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await expect(page.getByRole("tree", { name: "Files" })).toBeVisible();
  await page.getByRole("button", { name: "Terminal", exact: true }).click();
  await expect(page.locator(".kp-term")).toBeVisible();
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await expect(page.getByText("No saved Juno review for this sample session.")).toBeVisible();
  await page.goto("/w/dotrix/settings/rules");
  await expect(page.getByRole("heading", { name: "Rules for every project" })).toBeVisible();
  await page.getByLabel("Rules", { exact: true }).fill("Sample rules only");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Rules saved (v2)", { exact: true })).toBeVisible();
  for (const skill of ["write-an-adr", "triage-a-bug", "break-down-a-feature", "scope-a-failing-build"]) {
    await expect(page.getByText(skill, { exact: true })).toBeVisible();
  }
  await page.goto("/w/dotrix/settings/github");
  await expect(page.getByRole("heading", { name: "Connected repositories", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add a GitHub account", exact: true }).click();
  await expect(page.getByText("Sign in to connect your GitHub account. Sample connections are read-only.", { exact: true })).toBeVisible();
  await page.goto("/w/dotrix");
  await expect(page.locator(".ph h1")).toBeVisible();
  expect(await page.locator(".ph h1").evaluate((element) => getComputedStyle(element).fontFamily)).not.toContain("Serif");
  expect(errors).toEqual([]);
  expect(apiCalls).toEqual([]);
});

test("a live account uses the same navigation and typography without inheriting sample sessions", async ({ page }) => {
  await page.goto("/w/dotrix/codes");
  await expect(page.locator(".cs-row").first()).toBeVisible();
  const font = await page.locator(".chat-side h1").evaluate((element) => getComputedStyle(element).fontFamily);
  await signUp(page);
  const slug = new URL(page.url()).pathname.split("/")[2]!;
  await page.getByRole("navigation", { name: "Main", exact: true }).getByRole("button", { name: "Chat", exact: true }).click();
  await expect(page.locator(".chat-list .sitem")).toHaveCount(0);
  await expect(page.getByText("Sample conversation · Sign in to work with Nova.")).toHaveCount(0);
  await page.goto(`/w/${slug}/codes`);
  await expect(page.getByRole("heading", { name: "Codes", exact: true })).toBeVisible();
  await expect(page.locator(".cs-row")).toHaveCount(0);
  expect(await page.locator(".chat-side h1").evaluate((element) => getComputedStyle(element).fontFamily)).toBe(font);
});

for (const signedIn of [false, true]) {
  test(`sample session mutations stay disabled for ${signedIn ? "signed-in" : "signed-out"} visitors`, async ({ page }) => {
    if (signedIn) await signUp(page);
    await page.goto("/w/dotrix/codes");
    const errors: string[] = [];
    const apiCalls: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.startsWith("/v1/")) apiCalls.push(request.url());
    });
    await page.reload();
    await page.getByRole("button", { name: "More for WEB-154", exact: true }).click();
    const menu = page.getByRole("menu");
    await expect(menu.getByText("Sample session · Read-only", { exact: true })).toBeVisible();
    for (const action of ["Pin", "Rename", "Close session", "Archive", "Delete"]) {
      await expect(menu.getByRole("button", { name: action, exact: true })).toBeDisabled();
    }
    await expect(menu.getByRole("button", { name: "Open issue", exact: true })).toBeEnabled();
    await expect(menu.getByRole("button", { name: "Open PR", exact: true })).toBeEnabled();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    expect(errors).toEqual([]);
    expect(apiCalls).toEqual([]);
  });
}
