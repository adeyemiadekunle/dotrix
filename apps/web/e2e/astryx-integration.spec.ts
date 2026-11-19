import { expect, test } from "@playwright/test";

test("native controls keep their padding and color after the Astryx reset", async ({ page }) => {
  await page.goto("/w/dotrix");
  await expect(page.locator(".stat").first()).toHaveCSS("padding", "14px 16px");
  await page.goto("/w/dotrix/p/WEB/board");
  await expect(page.getByRole("navigation", { name: "Project views" }).getByRole("button", { name: "Board", exact: true })).toHaveCSS("padding", "0px 10px");
  const priority = await page
    .getByRole("button", { name: /^Priority:/ })
    .first()
    .boundingBox();
  expect(priority!.width).toBeGreaterThanOrEqual(24);
  expect(priority!.height).toBeGreaterThanOrEqual(24);
  await page.goto("/w/dotrix/settings/profile");
  await expect(page.locator(".sw").first()).not.toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  const colors = await page.locator(".sw").evaluateAll((elements) => elements.map((element) => getComputedStyle(element).backgroundColor));
  expect(new Set(colors).size).toBeGreaterThan(3);
});

test("Tailwind utilities resolve Astryx tokens and override component styles in both themes", async ({ page }) => {
  await page.goto("/w/dotrix");
  await expect(page.locator(".stat").first()).toBeVisible();
  await page.evaluate(() => {
    const probe = document.createElement("div");
    probe.id = "utility-contract";
    // These utilities are used by the real Knowledge mobile navigation.
    probe.className = "stat panel rounded-lg border border-border bg-surface p-3 text-primary";
    probe.textContent = "Theme-aware utility contract";
    document.querySelector("#main-content")!.prepend(probe);
  });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
    // Theme changes animate existing surfaces; assert their final token values.
    await expect(async () => {
      const result = await page.locator("#utility-contract").evaluate((element) => {
        const style = getComputedStyle(element);
        const reference = document.createElement("div");
        reference.style.cssText = "color:var(--color-text-primary);background:var(--color-background-surface);border-radius:var(--radius-container)";
        element.append(reference);
        const expected = getComputedStyle(reference);
        const result = {
          padding: style.padding,
          color: style.color,
          background: style.backgroundColor,
          radius: style.borderRadius,
          expectedColor: expected.color,
          expectedBackground: expected.backgroundColor,
          expectedRadius: expected.borderRadius,
        };
        reference.remove();
        return result;
      });
      expect(result.padding).toBe("12px");
      expect(result.color).toBe(result.expectedColor);
      expect(result.background).toBe(result.expectedBackground);
      expect(result.radius).toBe(result.expectedRadius);
    }).toPass({ timeout: 5000 });
  }
  const action = page.getByRole("button", { name: "New task", exact: true }).first();
  await action.evaluate((element) => element.classList.add("p-3", "rounded-lg"));
  await expect(action).toHaveCSS("padding", "12px");
  await expect(action).toHaveCSS("border-radius", "16px");
});

test("Knowledge switches between a full-width document and its tree on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/w/dotrix/p/WEB/knowledge");
  const reader = page.locator(".kn-grid > section");
  await expect(reader).toBeVisible();
  expect((await reader.boundingBox())!.width).toBeGreaterThan(320);
  await expect(page.locator(".kn-grid > aside")).toBeHidden();
  await page.locator(".kn-mobile-nav").getByRole("button", { name: "Documents", exact: true }).click();
  await expect(reader).toBeHidden();
  await page.getByRole("button", { name: "roadmap.md", exact: true }).click();
  await expect(reader).toBeVisible();
  await expect(reader.getByRole("heading", { name: "roadmap.md", exact: true })).toBeVisible();
});

for (const view of ["list", "knowledge?view=files"]) {
  test(`mobile ${view} toolbar contains its wrapped controls`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.goto(`/w/dotrix/p/WEB/${view}`);
    const toolbar = page.locator(".toolbar").first();
    await expect(toolbar).toBeVisible();
    const bounds = await toolbar.evaluate((element) => {
      const parent = element.getBoundingClientRect();
      return {
        bottom: parent.bottom,
        childBottoms: Array.from(element.children)
          .filter((child) => child.getBoundingClientRect().height > 0)
          .map((child) => child.getBoundingClientRect().bottom),
      };
    });
    for (const bottom of bounds.childBottoms) expect(bottom).toBeLessThanOrEqual(bounds.bottom + 1);
    if (view.includes("files")) {
      const drop = await page.locator(".dropzone").boundingBox();
      expect(drop!.y).toBeGreaterThanOrEqual(bounds.bottom);
    }
  });
}

for (const width of [390, 1440]) {
  test(`sample Codes header and Kai identity remain readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/w/dotrix/codes");
    await page.getByRole("button", { name: /WEB-154 Fix broken anchor links/ }).click();
    await expect(page.getByText("coding-agent", { exact: true })).toHaveCount(0);
    await expect(page.locator(".dotrix-message .who").filter({ hasText: "Kai" }).first()).toBeVisible();
    const buttons = await page.getByRole("group", { name: "Session panes" }).getByRole("button").all();
    let right = 0;
    for (const button of buttons) {
      const box = (await button.boundingBox())!;
      expect(box.width).toBeGreaterThanOrEqual(24);
      expect(box.x).toBeGreaterThanOrEqual(right);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      right = box.x + box.width;
    }
  });
}

test("sample Models renders without loading or accepting real keys", async ({ page }) => {
  const calls: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/v1/")) calls.push(request.url());
  });
  await page.goto("/w/dotrix/settings/my-models");
  await expect(page.getByRole("heading", { name: "Your keys", exact: true })).toBeVisible();
  await expect(page.getByText("Sample settings · Sign in to connect your own model keys.")).toBeVisible();
  await expect(page.getByText("Loading…", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Connect", exact: true })).toHaveCount(0);
  expect(calls).toEqual([]);
});

test("mobile Settings exposes the active section and navigates by group", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/w/dotrix/settings/profile");
  const sections = page.getByRole("combobox", { name: "Settings section", exact: true });
  await expect(sections).toHaveValue("profile");
  await expect(page.getByRole("navigation", { name: "Settings", exact: true })).toBeHidden();
  await sections.selectOption("preferences");
  await expect(page.getByRole("heading", { name: "Preferences", exact: true })).toBeVisible();
  await expect(sections).toHaveValue("preferences");
});

test("Inbox details stay top-aligned and pending notices do not cover Home", async ({ page }) => {
  await page.goto("/w/dotrix/inbox");
  await expect(page.locator(".inbox-prev")).toBeVisible();
  expect((await page.locator(".inbox-prev").boundingBox())!.y).toBeLessThan(100);
  await page.goto("/w/dotrix");
  const notice = page.getByRole("region", { name: "Waiting for you" });
  await expect(notice).toBeVisible();
  const box = (await notice.boundingBox())!;
  const heading = (await page.locator(".ph h1").boundingBox())!;
  expect(box.y + box.height).toBeLessThanOrEqual(heading.y);
  await expect(page.locator(".agents-launcher")).toHaveCSS("position", "static");
});

test("mobile task details use the viewport and preserve the issue key", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto("/w/dotrix");
  await page.getByText("Triage beta tester feedback", { exact: true }).first().click();
  const drawer = page.getByRole("dialog").filter({ has: page.locator(".drawer-key") });
  await expect(drawer).toBeVisible();
  await expect.poll(async () => Math.round((await drawer.boundingBox())!.width)).toBe(390);
  await expect(page.locator(".drawer-key")).toHaveCSS("white-space", "nowrap");
});

for (const width of [390, 1440]) {
  test(`workspace switcher stays aligned, announces selection and restores focus at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/w/dotrix");
    if (width === 390) await page.getByRole("button", { name: "Open navigation", exact: true }).click();
    const scope = width === 390 ? page.getByRole("dialog") : page.locator(".workspace-navigation");
    const trigger = scope.getByRole("button", { name: "Switch workspace", exact: true });
    await expect(trigger).toBeVisible();
    const alignment = await trigger.evaluate((element) => {
      const button = element.getBoundingClientRect();
      const logo = element.querySelector(".workspace-switcher-content > :first-child")!.getBoundingClientRect();
      const caret = element.querySelector(".workspace-switcher-caret")!.getBoundingClientRect();
      return { left: logo.left - button.left, right: button.right - caret.right };
    });
    expect(alignment.left).toBeLessThan(24);
    expect(alignment.right).toBeLessThan(24);
    await trigger.focus();
    await page.keyboard.press("ArrowDown");
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = page.getByRole("menu", { name: "Workspaces", exact: true });
    await expect(menu).toBeVisible();
    const current = menu.getByRole("menuitemradio", { checked: true });
    await expect(current).toHaveCount(1);
    await expect(current).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(menu.getByRole("menuitemradio", { name: /Personal/ })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  test(`composer plus is icon-only and its menu opens downward without losing the draft at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/w/dotrix/chat?new=1");
    await page.getByRole("radio", { name: "Website Redesign", exact: true }).check();
    const editor = page.getByLabel("Message", { exact: true });
    await editor.fill("Keep this unsent draft");
    const plus = page.getByRole("button", { name: "Project and mode", exact: true });
    expect((await plus.boundingBox())!.width).toBeLessThanOrEqual(40);
    await expect(plus).toHaveText("");
    const editorBounds = (await editor.boundingBox())!;
    expect((await plus.boundingBox())!.y).toBeGreaterThanOrEqual(editorBounds.y + editorBounds.height);
    await plus.click();
    const plan = page.getByRole("dialog").getByRole("button", { name: "Plan", exact: true });
    await expect(plan).toBeVisible();
    await expect
      .poll(async () => {
        const anchor = (await plus.boundingBox())!;
        const popup = (await page.getByRole("dialog").boundingBox())!;
        return popup.y >= anchor.y + anchor.height;
      })
      .toBe(true);
    await plan.click();
    await expect(editor).toHaveText("Keep this unsent draft");
    await expect(editor).toBeFocused();
  });
}

for (const width of [390, 1440]) {
  for (const area of ["chat", "codes"]) {
    test(`${area} keeps its model control before Send at ${width}px even without models`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/w/dotrix/${area}?new=1`);
      const composer = page.locator(".dotrix-composer");
      const model = composer.locator(".composer-model");
      await expect(model).toBeVisible();
      const send = composer.getByRole("button", { name: area === "chat" ? "Send" : "Start coding", exact: true });
      const input = composer.locator(area === "chat" ? '[contenteditable="true"]' : "textarea");
      const bounds = await model.boundingBox();
      const sendBounds = await send.boundingBox();
      const inputBounds = await input.boundingBox();
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(sendBounds!.x);
      expect(bounds!.y).toBeGreaterThanOrEqual(inputBounds!.y + inputBounds!.height);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      await expect(model.getByRole("button")).toBeDisabled();
    });
  }
}

for (const width of [390, 768, 1024, 1440]) {
  for (const area of ["chat", "codes"]) {
    test(`${area} sidebar hides completely and restores without losing a draft at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/w/dotrix/${area}?new=1`);
      const input = area === "chat" ? page.getByLabel("Message", { exact: true }) : page.getByRole("textbox", { name: "What should it do", exact: true });
      await input.fill("Keep this private draft");
      const aside = page.locator(".chat-side");
      if (width > 900) await aside.getByRole("button", { name: "Hide the list", exact: true }).click();
      await expect(aside).toBeHidden();
      const toggle = page.getByRole("button", { name: "Show the list", exact: true });
      await expect(toggle).toBeVisible();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      const mainBounds = (await page.locator(".chat-main").boundingBox())!;
      const gridBounds = (await page.locator(".chat-grid").boundingBox())!;
      expect(Math.abs(mainBounds.x - gridBounds.x)).toBeLessThan(1);
      expect(mainBounds.width).toBeGreaterThanOrEqual(gridBounds.width - 1);
      await toggle.click();
      await expect(aside).toBeVisible();
      await aside.getByRole("button", { name: "Hide the list", exact: true }).click();
      await expect(aside).toBeHidden();
      if (area === "chat") await expect(input).toHaveText("Keep this private draft");
      else await expect(input).toHaveValue("Keep this private draft");
      if (width > 900) {
        await page.reload();
        await expect(aside).toBeHidden();
        await expect(page.getByRole("button", { name: "Show the list", exact: true })).toBeVisible();
      }
    });
  }
}

for (const width of [390, 1440]) {
  for (const area of ["chat", "codes"]) {
    test(`${area} composer expands from a pill and keeps modes inside plus at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/w/dotrix/${area}?new=1`);
      if (area === "chat") await page.getByRole("radio", { name: "Website Redesign", exact: true }).check();
      const composer = page.locator(".compact-composer");
      const input = area === "chat" ? page.getByLabel("Message", { exact: true }) : page.getByRole("textbox", { name: "What should it do", exact: true });
      await page.getByRole("heading", { level: 2 }).click();
      const idleHeight = (await composer.boundingBox())!.height;
      expect(idleHeight).toBeLessThanOrEqual(64);
      await input.focus();
      expect((await composer.boundingBox())!.height).toBeGreaterThan(idleHeight + 20);
      await input.fill("Preserve this draft");
      await input.press("End");
      await input.press("Shift+Enter");
      await page.keyboard.insertText("While changing mode");
      const plus = page.getByRole("button", { name: area === "chat" ? "Project and mode" : "Code options", exact: true });
      const inputBox = (await input.boundingBox())!;
      expect((await plus.boundingBox())!.y).toBeGreaterThanOrEqual(inputBox.y + inputBox.height);
      await expect(page.getByRole("combobox", { name: /^(Coding mode|Follow-up mode)$/ })).toHaveCount(0);
      await plus.click();
      const menu = page.getByRole("dialog");
      const planName = area === "chat" ? "Plan" : "Plan (read only)";
      await menu.getByRole("button", { name: planName, exact: true }).click();
      await expect(input).toBeFocused();
      await plus.click();
      await expect(menu.getByRole("button", { name: planName, exact: true })).toHaveAttribute("aria-pressed", "true");
      await menu.getByRole("button", { name: area === "chat" ? "Discuss" : "Build", exact: true }).click();
      await expect(composer.locator(".cmp-mode")).toHaveCount(0);
      if (area === "chat") await expect(input).toHaveText("Preserve this draft\nWhile changing mode");
      else await expect(input).toHaveValue("Preserve this draft\nWhile changing mode");
    });
  }
}
