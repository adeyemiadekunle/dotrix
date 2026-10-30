import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const date = "2026-01-01T00:00:00Z";
const path = "src/components/Navigation.tsx";
const session = {
  session_id: "session1",
  project_id: "p1",
  project_key: "TEST",
  project_name: "Test project",
  issue_key: "TEST-1",
  issue_title: "Update navigation",
  title: "Update navigation",
  agent: "codex",
  status: "pr_opened",
  state: "idle",
  turns: 2,
  location: "cloud",
  started_at: date,
  updated_at: date,
  pinned: false,
  archived: false,
};

const turn = (number: number) => ({
  id: `turn${number}`,
  session_id: session.session_id,
  project_id: "p1",
  issue_key: "TEST-1",
  turn: number,
  agent: "codex",
  status: "pr_opened",
  location: "cloud",
  base_sha: "a4c18d2",
  branch: "test-branch",
  files_changed: [{ path, added: 1, removed: 1 }],
  screenshots: number === 2 ? [{ index: 0, name: "pricing.png", content_type: "image/png", size: 68 }] : [],
  events: [],
  summary: "Updated the navigation.",
  review_run_id: `review${number}`,
  created_at: date,
  updated_at: date,
});

const review = (number: number) => ({
  id: `review${number}`,
  agent: "reviewer",
  status: "completed",
  created_at: `2026-01-0${number}T00:00:00Z`,
  reply: `Review of turn ${number}`,
  sources: [],
  review_context: { coding_run_id: `turn${number}`, session_id: session.session_id, revision: `revision${number}` },
  outputs: [
    {
      id: `output${number}`,
      kind: "finding",
      items: [
        {
          index: 0,
          state: "open",
          data: {
            title: number === 2 ? "Keyboard focus is difficult to see" : "Earlier finding",
            detail: "The link needs a visible focus indicator.",
            suggested_fix: "Add a focus style.",
            severity: "medium",
            refs: [`${path}:2`],
          },
        },
      ],
    },
  ],
});

/** One of the session header's side-panel buttons (Changes, Files, Terminal, Review). */
const view = (page: Page, name: string) => page.getByRole("group", { name: "Side panel" }).getByRole("button", { name, exact: true });

async function mockWorkspace(
  page: Page,
  context: BrowserContext,
  baseURL: string,
  search = "codes?session=session1",
  openPanel = true,
  reviewAvailable = () => true,
) {
  await context.addCookies([{ name: "dx_session", value: "1", url: baseURL }]);
  await page.route("**/v1/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let data: unknown = [];
    if (pathname === "/v1/me") data = { id: "u1", display_name: "Test User", email: "test@example.com" };
    else if (pathname === "/v1/workspaces")
      data = [{ id: "w1", slug: "test-workspace", name: "Test workspace", kind: "personal", permissions: ["agents:code"] }];
    else if (pathname.endsWith("/members"))
      data = [{ user_id: "u1", display_name: "Test User", email: "test@example.com", role: "owner", sees_all_projects: true, project_ids: [] }];
    else if (pathname.endsWith("/projects"))
      data = [{ id: "p1", key: "TEST", name: "Test project", status: "active", access: "open", created_at: date, updated_at: date }];
    else if (pathname.endsWith("/model-access")) data = { ready: true };
    else if (pathname.endsWith("/coding/sessions/session1")) data = [turn(1), turn(2)];
    else if (pathname.endsWith("/coding/sessions")) data = [session];
    else if (pathname.endsWith("/diff"))
      data = {
        diff: `diff --git a/${path} b/${path}\n--- a/${path}\n+++ b/${path}\n@@ -1,3 +1,3 @@\n const nav = true;\n-const href = '/plans';\n+const href = '#plans';\n export { href };`,
      };
    else if (pathname.endsWith("/tree")) data = { base_sha: "a4c18d2", entries: [{ path, status: "modified", size: 50 }], truncated: false };
    else if (pathname.endsWith("/file"))
      data = {
        path,
        status: "modified",
        before: "const nav = true;\nconst href = '/plans';",
        after: "const nav = true;\nconst href = '#plans';",
        binary: false,
        too_large: false,
      };
    else if (pathname.endsWith("/events"))
      data = {
        events: [
          { kind: "tool", text: "Ran pnpm test", ref: "cmd1", at: date },
          { kind: "output", text: "24 tests passed", ref: "cmd1", at: date },
        ],
        next: null,
      };
    else if (pathname.endsWith("/agent/runs/review1")) data = review(1);
    else if (pathname.endsWith("/agent/runs/review2")) {
      if (!reviewAvailable()) {
        await route.fulfill({ status: 503, json: { detail: "Review unavailable" } });
        return;
      }
      data = review(2);
    } else if (pathname.includes("/screenshots/")) {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==", "base64"),
      });
      return;
    }
    await route.fulfill({ status: 200, json: data });
  });
  await page.goto(`/w/test-workspace/${search}`);
  if (openPanel) await view(page, "Changes").click();
}

test("the session header opens each view of the side panel, and Juno's findings show on their lines", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!);
  const panel = page.locator(".side-panel");
  await expect(view(page, "Changes")).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByText(path, { exact: true })).toBeVisible();
  // Juno's finding on line 2 sits under that line in the diff, and opens the review.
  await panel.getByRole("button", { name: /Juno's finding on line 2: Keyboard focus is difficult to see/ }).click();
  await expect(view(page, "Review")).toHaveAttribute("aria-pressed", "true");
  await view(page, "Files").click();
  await panel.getByRole("treeitem", { name: /Navigation.tsx/ }).click();
  await expect(panel.getByRole("button", { name: "Back to the files" })).toBeVisible();
  await view(page, "Terminal").click();
  await expect(panel.getByText("Recorded output · read-only")).toBeVisible();
  await expect(panel.getByText("24 tests passed")).toBeVisible();
  await view(page, "Files").click();
  await expect(panel.getByRole("button", { name: "Back to the files" })).toBeVisible();
  await expect(view(page, "Browser")).toHaveCount(0); // a live browser comes later
  await view(page, "Review").click();
  await expect(panel.getByText("Keyboard focus is difficult to see")).toBeVisible();
  await panel.getByRole("button", { name: "Ask Kai to fix" }).click();
  await expect(page.getByLabel("Follow-up")).toHaveValue(/Keyboard focus is difficult to see/);
  await panel.getByRole("button", { name: `${path}:2` }).click();
  await expect(view(page, "Files")).toHaveAttribute("aria-pressed", "true");
  await expect(panel.locator(".kp-line-reference")).toContainText("const href = '#plans'");
  await panel.getByRole("button", { name: "Back to the files" }).click();
  await view(page, "Review").click();
  await panel.getByRole("button", { name: `${path}:2` }).click();
  await expect(panel.locator(".kp-line-reference")).toBeVisible();
  await panel.getByLabel("Turn").selectOption("turn1");
  await view(page, "Review").click();
  await expect(panel.getByText("Earlier finding")).toBeVisible();
  await expect(panel.getByText("Superseded by a later coding turn")).toBeVisible();
  // The open view's button closes the panel, and the shortcut opens Changes again.
  await view(page, "Review").click();
  await expect(panel).toHaveCount(0);
  await page.keyboard.press("Control+Shift+D");
  await expect(view(page, "Changes")).toHaveAttribute("aria-pressed", "true");
});

test("the session shows Kai, never the engine underneath", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!, undefined, false);
  const main = page.locator(".conv-main");
  await expect(main.getByText("Kai", { exact: true }).first()).toBeVisible();
  await expect(page.getByLabel("Follow-up")).toHaveAttribute("placeholder", /Ask Kai/);
  await expect(page.locator(".chat-list")).not.toContainText("Codex");
  await expect(main).not.toContainText("Codex");
});

test("a file path in the session opens it in Files", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!, undefined, false);
  await page.locator(".chat-col").getByRole("button", { name: path, exact: true }).first().click();
  const panel = page.locator(".side-panel");
  await expect(view(page, "Files")).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByRole("button", { name: "Back to the files" })).toBeVisible();
  await expect(page).toHaveURL(/file=/);
});

test("a linked review reference opens its turn and file directly, from an older Chat link too", async ({ page, context, baseURL }) => {
  // Links from before Coding had its own page (chat?tab=coding&session=…) open the session in Coding.
  const search = new URLSearchParams({ tab: "coding", session: "session1", turn: "turn2", file: path, line: "2" });
  await mockWorkspace(page, context, baseURL!, `chat?${search}`, false);
  await expect(page).toHaveURL(/\/codes\?session=session1/);
  const panel = page.locator(".side-panel");
  await expect(view(page, "Files")).toHaveAttribute("aria-pressed", "true");
  await expect(panel.locator(".kp-line-reference")).toContainText("const href = '#plans'");
  await panel.getByRole("button", { name: "Close Files" }).click();
  await expect(panel).toHaveCount(0);
  await expect(page).not.toHaveURL(/file=/);
});

test("an unavailable review can be retried without showing a different turn's review", async ({ page, context, baseURL }) => {
  let available = false;
  await mockWorkspace(page, context, baseURL!, undefined, true, () => available);
  const panel = page.locator(".side-panel");
  await view(page, "Review").click();
  await expect(panel.getByText("Some reviews couldn't be loaded.")).toBeVisible({ timeout: 20_000 });
  await expect(panel.getByText("Earlier finding")).toHaveCount(0);
  available = true;
  await panel.getByRole("button", { name: "Try again" }).click();
  await expect(panel.getByText("Keyboard focus is difficult to see")).toBeVisible();
});

test("the work panel is closeable and keyboard accessible on mobile", async ({ page, context, baseURL }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockWorkspace(page, context, baseURL!);
  const panel = page.locator(".side-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("button", { name: "Close Changes" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(view(page, "Changes")).toBeFocused();
  await view(page, "Review").click();
  await panel.getByRole("button", { name: "Ask Kai to fix" }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByLabel("Follow-up")).toHaveValue(/Keyboard focus is difficult to see/);
});
