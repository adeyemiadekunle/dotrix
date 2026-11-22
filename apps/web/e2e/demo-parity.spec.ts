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
  const chatModel = page.getByRole("combobox", { name: "Model" });
  await chatModel.click();
  await page.getByRole("option", { name: "Sonnet 5.5" }).click();
  await expect(chatModel).toContainText("Sonnet 5.5");
  const message = page.getByRole("textbox", { name: "Message" });
  const compact = (await message.boundingBox())!.height;
  await message.fill("Help me plan the release");
  expect((await message.boundingBox())!.height).toBeGreaterThan(compact);
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
  await page.locator(".chat-list .sitem").first().click();
  await expect(page.getByText("Sample conversation · Sign in to work with Nova.")).toBeVisible();
  await expect(page.locator(".chat-msg").first()).toBeVisible();
  await page.goto("/w/dotrix/codes");
  await page.getByRole("button", { name: /WEB-154 Fix broken anchor links/ }).click();
  await expect(page.getByText("Sample session · Sign in to work with Kai.")).toBeVisible();
  const followUp = page.getByRole("textbox", { name: "Follow-up" });
  await expect(followUp).toBeInViewport();
  await followUp.fill("Check the remaining anchors");
  await followUp.press("Enter");
  await expect(followUp).toHaveValue("Check the remaining anchors");
  await expect(page.getByRole("link", { name: "Sign in to work with Kai." })).toHaveAttribute("href", "/login");
  await expect(page.locator(".chat-msg").first()).toBeVisible();
  await page.getByRole("button", { name: "Show the panes", exact: true }).click();
  await expect(page.getByRole("table", { name: "Diff" })).toHaveCount(3);
  await page.getByRole("button", { name: "Open a pane", exact: true }).click();
  await page.getByRole("menuitem", { name: "Files", exact: true }).click();
  await expect(page.getByRole("tree", { name: "Files" })).toBeVisible();
  await page.getByRole("button", { name: "Open a pane", exact: true }).click();
  await page.getByRole("menuitem", { name: "Terminal", exact: true }).click();
  await expect(page.locator(".kp-term")).toBeVisible();
  await page.getByRole("button", { name: "Open a pane", exact: true }).click();
  await page.getByRole("menuitem", { name: "Review", exact: true }).click();
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

test("sample workspace switches on Home and previews the repository-first Code composer", async ({ page }) => {
  await page.setViewportSize({ width: 1179, height: 812 });
  await page.goto("/w/dotrix");
  const switcher = page.getByRole("button", { name: "Switch workspace" });
  await switcher.click();
  await page.getByRole("button", { name: /Personal Free/ }).click();
  await expect(switcher).toContainText("Personal");
  await expect(page).toHaveURL(/\/w\/dotrix$/);

  await page.goto("/w/dotrix/codes");
  await expect(page.getByRole("combobox", { name: "Repository" })).toBeInViewport();
  await expect(page.getByRole("option", { name: "Cloud sandbox" })).toBeInViewport();
  await expect(page.getByRole("textbox", { name: "What should it do" })).toBeInViewport();
  await expect(page.getByRole("link", { name: "Sign in to start coding" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start coding" })).toBeDisabled();
  await expect(page.getByRole("separator", { name: "Resize the list" })).toHaveCount(0);
  const model = page.getByRole("combobox", { name: "Model", exact: true });
  await model.click();
  await page.getByRole("option", { name: "Sonnet 5.5" }).click();
  await expect(model).toContainText("Sonnet 5.5");

  const composer = page.locator(".compact-composer");
  const prompt = page.getByRole("textbox", { name: "What should it do" });
  const compact = (await composer.boundingBox())!.height;
  await prompt.fill("Fix navigation");
  expect((await composer.boundingBox())!.height).toBeGreaterThan(compact);
  await expect(composer).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await page.getByRole("heading", { name: "Start a session" }).click();
  expect((await composer.boundingBox())!.height).toBe(compact);
  await expect(prompt).toHaveValue("Fix navigation");

  const plus = page.getByRole("button", { name: "Code options" });
  const position = await plus.boundingBox();
  await plus.click();
  const options = page.getByRole("dialog", { name: "Code options" });
  await expect(options).toBeInViewport({ ratio: 1 });
  expect(await plus.boundingBox()).toEqual(position);
  await options.getByRole("button", { name: "Plan (read only)" }).click();
  await plus.click();
  await expect(options.getByRole("button", { name: "Plan (read only)" })).toHaveAttribute("aria-pressed", "true");
  await options.getByRole("button", { name: "Pick an issue" }).click();
  await expect(page.getByRole("listbox", { name: "Issues" })).toBeInViewport({ ratio: 1 });
  expect(await plus.boundingBox()).toEqual(position);

  await page.goto("/w/dotrix/codes?session=cs3");
  const toggle = page.getByRole("button", { name: "Show the panes" });
  await toggle.hover();
  expect(await page.locator(".content").evaluate((el) => el.scrollWidth)).toBe(await page.locator(".content").evaluate((el) => el.clientWidth));
  await toggle.click();
  const panel = page.getByRole("complementary", { name: "Session panes" });
  await expect(panel).toBeVisible();
  const bounds = (await panel.boundingBox())!;
  const header = (await page.locator(".cs-head").boundingBox())!;
  expect(bounds.x).toBeCloseTo(header.x + header.width);
  expect(bounds.y).toBe(header.y);
  const resize = panel.getByRole("separator", { name: "Resize the panes" });
  await expect(resize).toBeVisible();
  await resize.press("ArrowLeft");
  expect((await panel.boundingBox())!.width).toBeGreaterThan(bounds.width);
  await resize.press("ArrowRight");
  expect((await panel.boundingBox())!.width).toBeLessThanOrEqual(bounds.width + 1);
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
  await expect(page.getByRole("heading", { name: "Code", exact: true })).toBeVisible();
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
