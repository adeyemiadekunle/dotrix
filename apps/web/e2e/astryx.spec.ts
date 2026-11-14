import { expect, test } from "@playwright/test";

test("website theme follows the system with one main landmark and self-hosted typography", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/w/dotrix");
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(248, 244, 237)");
  await expect(page.locator("body")).toHaveCSS("font-family", /Figtree/);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(17, 17, 18)");
  expect(errors).toEqual([]);
});

test("saved accent, density and motion survive reload and reach dialogs", async ({ page }) => {
  await page.goto("/w/dotrix");
  await expect(page.getByRole("heading", { name: /Good/ })).toBeVisible();
  await page.keyboard.press("Control+Shift+l");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("dotrix.studio.v2"))).not.toBeNull();
  await page.evaluate(() => {
    const key = "dotrix.studio.v2";
    const saved = JSON.parse(localStorage.getItem(key)!);
    saved.prefs = { ...saved.prefs, theme: "light", accent: "indigo", density: "compact", motion: "reduce" };
    localStorage.setItem(key, JSON.stringify(saved));
  });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-accent", "indigo");
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await expect(page.locator("html")).toHaveAttribute("data-astryx-theme", "dotrix-reduced");
  await page.getByRole("button", { name: "New task", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Create task", exact: true })).toHaveCSS("background-color", "rgb(75, 91, 214)");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

for (const width of [390, 768, 1440]) {
  test(`shell and chat fit ${width}px and navigation stays accessible`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/w/dotrix/chat?new=1");
    await expect(page.getByLabel("Message", { exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width < 900) {
      const opener = page.getByRole("button", { name: "Open navigation", exact: true });
      await opener.click();
      const drawer = page.getByRole("dialog");
      await expect(drawer.getByRole("link", { name: "Codes", exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
      await expect(opener).toBeFocused();
    } else {
      await expect(page.getByRole("navigation", { name: "Conversations", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "New chat", exact: true })).toBeInViewport();
      const handle = page.getByRole("separator", { name: "Resize the list" });
      const before = await handle.getAttribute("aria-valuenow");
      await handle.focus();
      await page.keyboard.press("ArrowRight");
      await expect(handle).not.toHaveAttribute("aria-valuenow", before!);
    }
  });
}

test("composer mode suggestions preserve the plain-text draft", async ({ page }) => {
  await page.goto("/w/dotrix/chat?new=1");
  await page.getByRole("radio", { name: "Website Redesign", exact: true }).check();
  const message = page.getByLabel("Message", { exact: true });
  await message.fill("Review the navigation @Plan");
  await page.getByRole("option", { name: "Plan", exact: true }).click();
  await expect(message).toHaveText("Review the navigation ");
  await page.getByRole("button", { name: "Project and mode", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Plan", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("dialog").getByRole("button", { name: "Discuss", exact: true }).click();
  await expect(message).toHaveText("Review the navigation ");
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeEnabled();
});

test("command search keeps scope tabs and keyboard dismissal", async ({ page }) => {
  await page.goto("/w/dotrix");
  await expect(page.getByRole("button", { name: "Search and commands", exact: true })).toBeVisible();
  await page.keyboard.press("Control+k");
  const menu = page.getByRole("dialog", { name: "Command menu" });
  await expect(menu).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(menu.getByRole("navigation", { name: "Search scope" })).toBeVisible();
  await menu.getByRole("button", { name: "Tasks", exact: true }).click();
  await expect(menu.getByRole("button", { name: "Tasks", exact: true })).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
});

test("auth inputs retain native form values and password semantics", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill("ada@example.com");
  await page.getByLabel("Password", { exact: true }).fill("correct horse battery staple");
  const values = await page
    .locator("form")
    .first()
    .evaluate((form) => Object.fromEntries(new FormData(form as HTMLFormElement)));
  expect(values).toMatchObject({ email: "ada@example.com", password: "correct horse battery staple" });
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute("type", "password");
});

test("a date picker dismisses before its task form and keeps the draft", async ({ page }) => {
  await page.goto("/w/dotrix");
  await page.getByRole("button", { name: "New task", exact: true }).first().click();
  const form = page.getByRole("dialog", { name: "New task", exact: true });
  await form.getByLabel("Task name", { exact: true }).fill("Check the Astryx migration");
  await form.getByRole("button", { name: "Due date", exact: true }).click();
  const picker = page.locator(".pop.floating");
  await expect(picker).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(picker).toBeHidden();
  await expect(form).toBeVisible();
  await expect(form.getByLabel("Task name", { exact: true })).toHaveValue("Check the Astryx migration");
  await form.getByRole("button", { name: "Create task", exact: true }).click();
  await expect(form).toBeHidden();
  await page.getByRole("button", { name: "Open", exact: true }).last().click();
  await expect(page.getByRole("dialog", { name: "Task: Check the Astryx migration", exact: true })).toBeVisible();
});
