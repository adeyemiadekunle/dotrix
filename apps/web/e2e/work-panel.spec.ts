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
  before: () => Promise<void> = async () => {},
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
  await before(); // routes added here win over the ones above
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
  await expect(page.getByRole("menuitemcheckbox", { name: /^Browser/ })).toHaveCount(0); // the Browser pane is in the desktop app only
  await expect(review.getByText("Keyboard focus is difficult to see")).toBeVisible();
  // Juno's review details are keyboard tabs.
  await review.getByRole("tab", { name: /^Findings/ }).click();
  await review.getByRole("tab", { name: /^Findings/ }).press("ArrowRight");
  await expect(review.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true");
  await review.getByRole("tab", { name: "Summary" }).click();
  await review.getByRole("tab", { name: /^Findings/ }).click();
  await review.getByRole("button", { name: "Ask Kai to fix" }).click();
  await expect(page.getByRole("textbox", { name: "Follow-up", exact: true })).toHaveValue(/Keyboard focus is difficult to see/);
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
  await expect(page.getByRole("combobox", { name: "Follow-up mode", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Follow-up", exact: true })).toHaveAttribute("placeholder", /Ask Kai/);
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
  await expect(page.getByRole("textbox", { name: "Follow-up", exact: true })).toHaveValue(/Keyboard focus is difficult to see/);
});

test("live session menus still pin using the current workspace and project scope", async ({ page, context, baseURL }) => {
  await mockWorkspace(page, context, baseURL!, "codes", false);
  await page.route("**/coding/sessions/session1", (route) =>
    route.request().method() === "PATCH" ? route.fulfill({ json: { ...session, pinned: true } }) : route.fallback(),
  );
  await page.getByRole("button", { name: "More for TEST-1", exact: true }).click();
  const pin = page.getByRole("menu").getByRole("button", { name: "Pin", exact: true });
  await expect(pin).toBeEnabled();
  const submitted = page.waitForRequest((request) => request.method() === "PATCH" && new URL(request.url()).pathname.endsWith("/coding/sessions/session1"));
  await pin.click();
  const request = await submitted;
  expect(new URL(request.url()).pathname).toBe("/v1/workspaces/w1/projects/p1/coding/sessions/session1");
  expect(request.postDataJSON()).toEqual({ pinned: true });
});

test("a working turn is followed over a stream: what Kai does appears without polling", async ({ page, context, baseURL }) => {
  const working = { ...turn(2), status: "running", summary: null, files_changed: [], review_run_id: null, event_count: 1 };
  const said = (text: string) => ({ seq: 0, kind: "text", text, at: date });
  let reads = 0;
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await mockWorkspace(page, context, baseURL!, "codes?session=session1", false, undefined, async () => {
    await page.route("**/coding/sessions/session1", async (route) => {
      reads += 1;
      await route.fulfill({ status: 200, json: [turn(1), { ...working, events: [said("Reading the navigation")] }] });
    });
    // The stream: the turn as it works, then (once the test lets it) finished, and the end.
    await page.route("**/coding/sessions/session1/stream", async (route) => {
      await held;
      const frame = (turns: unknown) => `event: turns\ndata: ${JSON.stringify(turns)}\n\n`;
      const done = { ...turn(2), summary: "Pointed the plans link at the page's own section.", events: [said("Reading the navigation")] };
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: frame([turn(1), done]) + "event: end\ndata: {}\n\n" });
    });
  });
  await expect(page.getByText("Kai is working")).toBeVisible();
  release();
  await expect(page.getByText("Pointed the plans link at the page's own section.")).toBeVisible();
  // The finished turn came over the stream: the page didn't ask for the session again.
  expect(reads).toBe(1);
});

test("file/diff text, line annotations, syntax colors and path copying survive both themes", async ({ page, context, baseURL }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseURL! });
  await page.emulateMedia({ colorScheme: "light" });
  await mockWorkspace(page, context, baseURL!);
  const changes = pane(page, "Changes");
  await expect(changes.locator(".kp-line.del .kp-text")).toHaveText("const href = '/plans';");
  await expect(changes.locator(".kp-line.add .kp-text")).toHaveText("const href = '#plans';");
  await expect(changes.locator(".kp-line.add .kp-no")).toHaveText(["", "2"]);
  await expect(changes.locator(".kp-line.del .kp-no")).toHaveText(["2", ""]);
  const finding = changes.getByRole("button", { name: /Juno's finding on line 2:/ });
  await expect(finding).toBeVisible();
  expect(await finding.evaluate((el) => el.previousElementSibling?.classList.contains("add"))).toBe(true);
  const token = changes.locator(".kp-line.add .kp-tok").first();
  await expect(token).toBeVisible();
  const light = await token.evaluate((el) => getComputedStyle(el).color);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(token).not.toHaveCSS("color", light);
  await barButton(page, "Files").click();
  const files = pane(page, "Files");
  await files.getByRole("treeitem", { name: /Navigation.tsx/ }).click();
  await expect(files.locator(".kp-source .kp-text")).toHaveText(["const nav = true;", "const href = '#plans';"]);
  await expect(files.getByRole("rowheader")).toHaveText(["1", "2"]);
  await files.getByRole("button", { name: "Copy the path", exact: true }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(path);
});

test("unknown-language files keep whitespace/escaped text and scroll inside the mobile pane", async ({ page, context, baseURL }) => {
  const source = '\t<not-an-element> & "literal"\n' + "long_" + "x".repeat(700) + "\n";
  const rawPath = "raw.unknown-dotrix-language";
  await page.setViewportSize({ width: 390, height: 844 });
  await mockWorkspace(page, context, baseURL!, `codes?session=session1&file=${rawPath}&line=2`, false, undefined, async () => {
    await page.route("**/coding/runs/*/file?**", (route) =>
      route.fulfill({ json: { path: rawPath, status: "modified", after: source, binary: false, too_large: false } }),
    );
  });
  const files = pane(page, "Files");
  const viewer = files.locator(".kp-source");
  await expect.poll(() => viewer.locator(".kp-text").allTextContents()).toEqual(source.split("\n").slice(0, -1));
  await expect(viewer.locator("not-an-element, .kp-tok")).toHaveCount(0);
  await expect(viewer.locator(".kp-line-reference")).toContainText("long_");
  expect(await viewer.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

for (const state of ["binary", "too_large", "deleted"] as const) {
  test(`file viewer protects the ${state} state without displaying hidden content`, async ({ page, context, baseURL }) => {
    await mockWorkspace(page, context, baseURL!, `codes?session=session1&file=${path}`, false, undefined, async () => {
      await page.route("**/coding/runs/*/file?**", (route) =>
        route.fulfill({
          json: {
            path,
            status: state === "deleted" ? "deleted" : "modified",
            after: "must not be rendered",
            binary: state === "binary",
            too_large: state === "too_large",
          },
        }),
      );
    });
    const files = pane(page, "Files");
    await expect(
      files.getByText(state === "binary" ? "A binary file: not shown." : state === "too_large" ? "Over 1 MB: not shown." : "The turn deleted this file.", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(files.locator(".kp-source")).toHaveCount(0);
    await expect(files.getByText("must not be rendered")).toHaveCount(0);
  });
}
