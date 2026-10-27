import { expect, test } from "@playwright/test";

test("new chat is visible and preserves the full approval mode", async ({ page }) => {
  await page.goto("/w/dotrix/chat");
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await expect(page).toHaveURL(/\/chat\?new=1$/);
  const approval = page.getByRole("button", { name: "Approvals: Manual" });
  await expect(approval).toBeVisible();
  expect(await approval.locator("span").evaluate((el) => el.clientWidth >= el.scrollWidth)).toBe(true);
  await page.getByRole("button", { name: "Hide the list" }).click();
  await expect(page.getByRole("button", { name: "New chat", exact: true })).toBeVisible();
});

test("mobile Home keeps decisions and notices visible, and keyboard navigation works", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/w/dotrix");
  const heading = page.getByRole("heading", { level: 1 });
  const notice = page.getByRole("region", { name: "Waiting for you" });
  const decision = page.getByRole("heading", { name: "Waiting for a decision" });
  const stats = page.getByRole("button", { name: /Active projects/ });
  await expect(notice).toBeVisible();
  await expect(decision).toBeVisible();
  expect((await notice.boundingBox())!.y + (await notice.boundingBox())!.height).toBeLessThanOrEqual((await heading.boundingBox())!.y);
  expect((await decision.boundingBox())!.y).toBeLessThan((await stats.boundingBox())!.y);
  await expect(page.locator("nav.side")).toHaveAttribute("inert", "");
  const opener = page.getByRole("button", { name: "Open navigation" });
  await opener.click();
  await expect(page.getByRole("button", { name: "Close menu" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(opener).toBeFocused();
  await expect(page.locator("nav.side")).toHaveAttribute("inert", "");
  const upcoming = page.getByRole("tab", { name: /Upcoming/ });
  await upcoming.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: /Overdue/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: /Overdue/ })).toBeFocused();
  await page.getByRole("region", { name: "Waiting for you" }).getByRole("button", { name: "Open", exact: true }).click();
  await expect(page).toHaveURL(/\/inbox\?n=na1/);
  await page.goto("/w/dotrix/chat");
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await expect(page.getByLabel("Message")).toBeVisible();
  await page.getByRole("button", { name: "Back to conversations" }).click();
  await expect(page.getByRole("button", { name: "New chat", exact: true })).toBeVisible();
});

test("demo decision opens its Inbox detail rather than an endless conversation loader", async ({ page }) => {
  await page.goto("/w/dotrix");
  await page.getByRole("button", { name: /Nova wants to change/ }).click();
  await expect(page).toHaveURL(/\/inbox\?n=na1/);
  await expect(page.getByText("requirements/navigation.md").first()).toBeVisible();
  await page.goto("/w/dotrix/chat?thread=th1");
  await expect(page.getByText("This conversation isn't available in the demo. Review the request in Inbox.")).toBeVisible();
  await page.getByRole("button", { name: "Open Inbox" }).click();
  await expect(page).toHaveURL(/\/inbox\?tab=needs/);
  const needs = page.getByRole("tab", { name: /Needs you/ });
  await expect(needs).toHaveAttribute("aria-selected", "true");
  await needs.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: /Mentions/ })).toHaveAttribute("aria-selected", "true");
});

test("a live conversation shows the Dotrix loader, then an actionable failure", async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: "dx_session", value: "1", url: baseURL! }]);
  let release!: () => void;
  const pending = new Promise<void>((resolve) => (release = resolve));
  let runCalls = 0;
  await page.route("**/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (path === "/v1/me") data = { id: "u1", display_name: "Test User", email: "test@example.com" };
    else if (path === "/v1/workspaces") data = [{ id: "w1", slug: "test-workspace", name: "Test workspace", kind: "personal", permissions: [] }];
    else if (path.endsWith("/members"))
      data = [{ user_id: "u1", display_name: "Test User", email: "test@example.com", role: "owner", sees_all_projects: true, project_ids: [] }];
    else if (path.endsWith("/projects"))
      data = [
        {
          id: "p1",
          key: "TEST",
          name: "Test project",
          status: "active",
          access: "open",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ];
    else if (path.endsWith("/model-access")) data = { ready: true };
    else if (path.endsWith("/agent/runs")) {
      runCalls += 1;
      if (runCalls === 1) {
        await pending;
        await route.fulfill({ status: 400, json: { detail: "Unavailable" } });
        return;
      }
    }
    await route.fulfill({ status: 200, json: data });
  });
  await page.goto("/w/test-workspace/chat?thread=thread1&project=TEST");
  const loading = page.getByRole("status").filter({ hasText: "Loading the conversation" });
  await expect(loading).toBeVisible();
  await expect(loading.getByRole("img", { name: "Loading" })).toBeVisible();
  const dot = loading.locator(".dots-loader-dot").first();
  await expect(dot).toHaveCSS("animation-name", "dots-pulse");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(dot).toHaveCSS("animation-name", "none");
  release();
  await expect(page.getByText("The conversation couldn't be loaded.")).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("This conversation isn't here: it was deleted, or isn't one you can see.")).toBeVisible();
});
