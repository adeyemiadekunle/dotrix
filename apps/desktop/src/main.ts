// Desktop shell (FR-39): a native window around the web app, plus OS integration
// (tray, notifications for pending approvals, deep links) added over time. It also codes local turns
// itself (runner.ts): the bundled dotrix CLI's runner, for the folders a person picks.
import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent, Notification, shell } from "electron";
import path from "node:path";

import { Browser } from "./browser";
import { KaiBrowser } from "./browserKai";
import { DevServers, KaiApp } from "./devServer";
import { McpServer, type ToolSet } from "./mcp";
import { readChangelog } from "./changelog";
import { webUrl } from "./config";
import { opensOutside, staysInside } from "./links";
import { Runners, sameOrigin } from "./runner";
import { Updates } from "./updates";
import { notify } from "./notify";
import { ownWorktree, worktreeFile, worktreeTree } from "./worktree";

const WEB_URL = webUrl();
// The web app is served on the API's origin, so the runner talks to the same one unless told otherwise.
const API_URL = process.env.DOTRIX_API_URL ?? new URL(WEB_URL).origin;

let browser: Browser; // the Browser pane's profile and rules (made once the app is ready)
let kai: KaiBrowser; // Kai's use of the pane on a turn coding here
let kaiTools: McpServer | null = null; // where that turn's coding tool reaches it
let devServers: DevServers; // the app Kai starts in its worktree, with the command a person saved
// A runner hands its coding tool the pane's tools: where they are, and a token of its own folder's (dotrix_cli/runner.py).
const runners = new Runners(
  API_URL,
  WEB_URL,
  (folder): Record<string, string> => (kaiTools?.url ? { DOTRIX_BROWSER_MCP_URL: kaiTools.url, DOTRIX_BROWSER_MCP_TOKEN: kaiTools.tokenFor(folder) } : {}),
  (folder) => void devServers?.stop(folder),
);
/** The coding session and issue of the turn a folder's runner is coding now, or null. */
const turnOf = (folder: string) => {
  const turn = runners.list().find((runner) => runner.folder === folder)?.turn;
  return turn?.sessionId ? { sessionId: turn.sessionId, issueKey: turn.issueKey } : null;
};
/** The worktree a folder's runner is coding in now (one the runner made), or null. */
const worktreeOf = (folder: string) => ownWorktree(runners.list().find((runner) => runner.folder === folder)?.turn?.worktree);
/** The app's own page, where the pane lives. */
const appPage = () => BrowserWindow.getAllWindows().find((win) => !win.isDestroyed() && sameOrigin(win.webContents.getURL(), WEB_URL))?.webContents ?? null;
let stopped = false; // the runners were stopped for quitting (or restarting into an update)
// A turn coding here is stopped (the tool with it) before the app restarts into a new version.
const updates = new Updates(async () => {
  stopped = true;
  await Promise.all([runners.stopAll(), devServers?.stopAll()]);
});

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "dotrix",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      // The Browser pane's tabs (browser.ts): each is checked in will-attach-webview below.
      webviewTag: true,
    },
  });

  // A tab of the Browser pane: only from the app's own page, and only in the pane's own profile.
  win.webContents.on("will-attach-webview", (event, webPreferences, params) => {
    if (!sameOrigin(win.webContents.getURL(), WEB_URL) || !browser.attach(webPreferences, params)) event.preventDefault();
  });

  // Open external links in the system browser, never inside the app window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (opensOutside(url)) void shell.openExternal(url);
    return { action: "deny" };
  });

  // The window stays on dotrix (and GitHub's sign-in pages): any other page is refused, and opened in the browser when it is a web link.
  const keepInside = (event: { preventDefault(): void }, url: string): void => {
    if (staysInside(url, WEB_URL)) return;
    event.preventDefault();
    if (opensOutside(url)) void shell.openExternal(url);
  };
  win.webContents.on("will-navigate", (event, url) => keepInside(event, url));
  win.webContents.on("will-redirect", (event, url) => keepInside(event, url));

  void win.loadURL(WEB_URL);
}

/** Only the app's own web page may use the runner and the worktrees, never another page it shows. */
function handle(channel: string, fn: (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown): void {
  ipcMain.handle(channel, (event, ...args) => {
    if (!sameOrigin(event.senderFrame?.url ?? "", WEB_URL)) throw new Error("Not allowed from this page");
    return fn(event, ...args);
  });
}

function worktree(tree: unknown): string {
  const found = ownWorktree(tree);
  if (!found) throw new Error("Not a worktree of this computer's runner");
  return found;
}

function bridge(): void {
  const parent = (event: IpcMainInvokeEvent) => BrowserWindow.fromWebContents(event.sender);
  handle("dotrix:runners:list", () => runners.list());
  handle("dotrix:runners:add", (event, workspace: unknown, projectKey: unknown) => {
    if (typeof workspace !== "string" || typeof projectKey !== "string") throw new Error("Which project?");
    return runners.add(parent(event), workspace, projectKey);
  });
  handle("dotrix:runners:remove", (_e, folder: unknown) => typeof folder === "string" && runners.remove(folder));
  handle("dotrix:runners:restart", (_e, folder: unknown) => typeof folder === "string" && runners.restart(folder));
  handle("dotrix:runners:sign-in", (event) => runners.signIn(parent(event)));
  handle("dotrix:worktree:tree", (_e, tree: unknown) => worktreeTree(worktree(tree)));
  handle("dotrix:worktree:file", (_e, tree: unknown, file: unknown) => worktreeFile(worktree(tree), file));
  handle("dotrix:worktree:open", async (_e, tree: unknown) => {
    const error = await shell.openPath(worktree(tree));
    if (error) throw new Error(error);
  });
  handle("dotrix:worktree:reveal", (_e, tree: unknown) => shell.showItemInFolder(worktree(tree)));
  handle("dotrix:app:info", () => ({ version: app.getVersion(), platform: process.platform, packaged: app.isPackaged }));
  handle("dotrix:app:changelog", () => readChangelog(process.resourcesPath, app.isPackaged));
  handle("dotrix:updates:state", () => updates.state);
  handle("dotrix:updates:check", () => updates.check());
  handle("dotrix:updates:install", () => updates.install());
  handle("dotrix:notify:show", (event, notice: unknown) => notify(event.sender, notice));
  handle("dotrix:notify:supported", () => Notification.isSupported());
  handle("dotrix:browser:settings", () => browser.settings);
  handle("dotrix:browser:keep-cookies", (_e, keep: unknown) => browser.setKeepCookies(keep === true));
  handle("dotrix:browser:clear", () => browser.clear());
  handle("dotrix:browser:enabled", (_e, enabled: unknown) => browser.setEnabled(enabled === true));
  handle("dotrix:dev-servers:list", () => devServers.commands);
  handle("dotrix:dev-servers:save", (_e, folder: unknown, given: unknown) => {
    // Only a folder this computer codes in (one of its runners').
    if (typeof folder !== "string" || !runners.list().some((runner) => runner.folder === folder)) throw new Error("Not one of this computer's folders");
    return devServers.save(folder, given && typeof given === "object" ? (given as { command?: unknown; port?: unknown }) : null);
  });
  handle("dotrix:browser:kai-allowed", (_e, allowed: unknown) => browser.setKaiAllowed(allowed === true));
  handle("dotrix:browser:kai-request", () => kai.requests);
  handle("dotrix:browser:kai-ready", (event, id: unknown, contentsId: unknown) => kai.ready(event.sender, id, contentsId));
}

app.whenReady().then(async () => {
  browser = new Browser();
  kai = new KaiBrowser(
    appPage,
    () => browser.settings.enabled && browser.settings.kaiAllowed,
    () => browser.settings.partition,
    turnOf,
  );
  browser.kais = (tab) => kai.owns(tab);
  devServers = new DevServers();
  const kaiApp = new KaiApp(devServers, worktreeOf, () => browser.settings.enabled && browser.settings.kaiAllowed);
  // The pane's tools, and the app's for a folder with a saved command.
  const tools: ToolSet = {
    list: (folder) => [...kai.list(), ...kaiApp.list(folder)],
    call: (name, args, folder) => (name.startsWith("app_") ? kaiApp.call(name, folder) : kai.call(name, args, folder)),
  };
  kaiTools = new McpServer("dotrix-browser", app.getVersion(), tools);
  // Without it the app works as before: Kai's local turns just have no browser.
  await kaiTools.start().catch(() => (kaiTools = null));
  app.on("web-contents-created", (_event, contents) => {
    if (contents.getType() !== "webview") return;
    browser.watch(contents);
    kai.hear(contents);
  });
  bridge();
  createWindow();
  runners.resume();
  updates.start();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// A turn in progress is stopped (the tool with it) before the app goes, not left coding unwatched; and an app
// Kai started is stopped too (it runs in a process group of its own, so it would outlive this one).
app.on("before-quit", (event) => {
  if (stopped || (!runners.running && !devServers?.active)) return;
  event.preventDefault();
  void Promise.all([runners.stopAll(), devServers?.stopAll()]).finally(() => {
    stopped = true;
    app.quit();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
