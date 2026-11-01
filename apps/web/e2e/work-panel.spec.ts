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

/** A pane beside the session (Changes, Files, Terminal, Review); several can be open, stacked. */
const pane = (page: Page, name: string) => page.locator(`.side-panel section.pane[aria-label="${name}"]`);
/** Opens or closes a pane from the session bar's menu of panes (the "…"). */
async function toggle(page: Page, name: string) {
  const menuButton = page.getByRole("button", { name: "Panes", exact: true });
  await menuButton.click();
  await page.getByRole("menuitemcheckbox", { name: new RegExp(`^${name}`) }).click();
  await menuButton.click();
}
/** The session bar's own buttons for Changes and Files. */
const barButton = (page: Page, name: string) => page.getByRole("group", { name: "Session panes" }).getByRole("button", { name, exact: true });

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
  if (openPanel) await barButton(page, "Changes").click();
}

test("the session bar opens panes beside it, stacked, and Juno's findings show on their lines", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!);
  const changes = pane(page, "Changes");
  await expect(barButton(page, "Changes")).toHaveAttribute("aria-pressed", "true");
  await expect(changes.getByText(path, { exact: true })).toBeVisible();
  // Juno's finding on line 2 sits under that line in the diff, and opens the review beside it.
  await changes.getByRole("button", { name: /Juno's finding on line 2: Keyboard focus is difficult to see/ }).click();
  const review = pane(page, "Review");
  await expect(review).toBeVisible();
  await expect(changes).toBeVisible(); // panes stack: Changes stays open
  await barButton(page, "Files").click();
  const files = pane(page, "Files");
  await files.getByRole("treeitem", { name: /Navigation.tsx/ }).click();
  await expect(files.getByRole("button", { name: "Back to the files" })).toBeVisible();
  await toggle(page, "Terminal");
  const terminal = pane(page, "Terminal");
  await expect(terminal.getByText("Recorded output · read-only")).toBeVisible();
  await expect(terminal.getByText("24 tests passed")).toBeVisible();
  await expect(page.getByRole("menuitemcheckbox", { name: /^Browser/ })).toHaveCount(0); // a live browser comes later
  await expect(review.getByText("Keyboard focus is difficult to see")).toBeVisible();
  // Juno's review details are keyboard tabs.
  await review.getByRole("tab", { name: /^Findings/ }).click();
  await review.getByRole("tab", { name: /^Findings/ }).press("ArrowRight");
  await expect(review.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true");
  await review.getByRole("tab", { name: "Summary" }).click();
  await review.getByRole("tab", { name: /^Findings/ }).click();
  await review.getByRole("button", { name: "Ask Kai to fix" }).click();
  await expect(page.getByLabel("Follow-up")).toHaveValue(/Keyboard focus is difficult to see/);
  // A reference in the review opens its line in Files.
  await toggle(page, "Terminal");
  await review.getByRole("button", { name: `${path}:2` }).click();
  await expect(files.locator(".kp-line-reference")).toContainText("const href = '#plans'");
  await files.getByRole("button", { name: "Back to the files" }).click();
  await review.getByRole("button", { name: `${path}:2` }).click();
  await expect(files.locator(".kp-line-reference")).toBeVisible();
  // A turn's changes chip in the transcript shows that turn in every pane.
  await page.locator(".kt").first().locator(".kt-lines").first().click();
  await expect(review.getByText("Earlier finding")).toBeVisible();
  await expect(review.getByText("Superseded by a later coding turn")).toBeVisible();
  // A pane's close button closes just that pane; "Close all panes" the rest; the shortcut opens Changes again.
  await review.getByRole("button", { name: "Close Review" }).click();
  await expect(review).toHaveCount(0);
  await expect(changes).toBeVisible();
  await page.getByRole("button", { name: "Panes", exact: true }).click();
  await page.getByRole("menuitem", { name: /Close all panes/ }).click();
  await expect(page.locator(".side-panel")).toHaveCount(0);
  await page.keyboard.press("Control+Shift+D");
  await expect(barButton(page, "Changes")).toHaveAttribute("aria-pressed", "true");
});

test("a pane expands to the whole column and back", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!);
  await barButton(page, "Files").click();
  await pane(page, "Changes").getByRole("button", { name: "Expand Changes" }).click();
  await expect(pane(page, "Files")).toHaveCount(0);
  await pane(page, "Changes").getByRole("button", { name: "Show the other panes" }).click();
  await expect(pane(page, "Files")).toBeVisible();
  await expect(page).toHaveURL(/panel=changes%2Cfiles|panel=changes,files/);
});

test("the session shows Kai, never the engine underneath", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!, undefined, false);
  const main = page.locator(".conv-main");
  await expect(main.getByText("Kai", { exact: true }).first()).toBeVisible();
  await expect(page.getByLabel("Follow-up")).toHaveAttribute("placeholder", /Ask Kai/);
  await expect(page.locator(".chat-list")).not.toContainText("Codex");
  await expect(main).not.toContainText("Codex");
});

test("a file in the session's details opens it in Files", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!, undefined, false);
  const details = page.getByRole("complementary", { name: "Session details" });
  await expect(details.getByText("Cloud")).toBeVisible();
  await details.getByRole("button", { name: `Open ${path} in Files` }).click();
  await expect(barButton(page, "Files")).toHaveAttribute("aria-pressed", "true");
  await expect(pane(page, "Files").getByRole("button", { name: "Back to the files" })).toBeVisible();
  await expect(page).toHaveURL(/file=/);
});

test("a linked review reference opens its turn and file directly, from an older Chat link too", async ({ page, context, baseURL }) => {
  // Links from before Coding had its own page (chat?tab=coding&session=…) open the session in Coding.
  const search = new URLSearchParams({ tab: "coding", session: "session1", turn: "turn2", file: path, line: "2" });
  await mockWorkspace(page, context, baseURL!, `chat?${search}`, false);
  await expect(page).toHaveURL(/\/codes\?session=session1/);
  const files = pane(page, "Files");
  await expect(barButton(page, "Files")).toHaveAttribute("aria-pressed", "true");
  await expect(files.locator(".kp-line-reference")).toContainText("const href = '#plans'");
  await files.getByRole("button", { name: "Close Files" }).click();
  await expect(page.locator(".side-panel")).toHaveCount(0);
  await expect(page).not.toHaveURL(/file=/);
});

test("an unavailable review can be retried without showing a different turn's review", async ({ page, context, baseURL }) => {
  let available = false;
  await mockWorkspace(page, context, baseURL!, undefined, true, () => available);
  await toggle(page, "Review");
  const review = pane(page, "Review");
  await expect(review.getByText("Some reviews couldn't be loaded.")).toBeVisible({ timeout: 20_000 });
  await expect(review.getByText("Earlier finding")).toHaveCount(0);
  available = true;
  await review.getByRole("button", { name: "Try again" }).click();
  await expect(review.getByText("Keyboard focus is difficult to see")).toBeVisible();
});

test("the panes are closeable and keyboard accessible on mobile", async ({ page, context, baseURL }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockWorkspace(page, context, baseURL!);
  const panel = page.locator(".side-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("button", { name: "Close Changes" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(barButton(page, "Changes")).toBeFocused();
  // The session bar stays above the panes, so its menu opens other panes over them.
  await toggle(page, "Review");
  await pane(page, "Review").getByRole("button", { name: "Ask Kai to fix" }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.getByLabel("Follow-up")).toHaveValue(/Keyboard focus is difficult to see/);
});
