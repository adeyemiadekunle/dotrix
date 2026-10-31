// Desktop shell (FR-39): a native window around the web app, plus OS integration
// (tray, notifications for pending approvals, deep links) added over time. It also codes local turns
// itself (runner.ts): the bundled dotrix CLI's runner, for the folders a person picks.
import { app, BrowserWindow, ipcMain, type IpcMainInvokeEvent, shell } from "electron";
import path from "node:path";

import { webUrl } from "./config";
import { Runners, sameOrigin } from "./runner";
import { ownWorktree, worktreeFile, worktreeTree } from "./worktree";

const WEB_URL = webUrl();
// The web app is served on the API's origin, so the runner talks to the same one unless told otherwise.
const API_URL = process.env.DOTRIX_API_URL ?? new URL(WEB_URL).origin;

const runners = new Runners(API_URL, WEB_URL);

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "dotrix",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
    },
  });

  // Open external links in the system browser, never inside the app window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

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
}

app.whenReady().then(() => {
  bridge();
  createWindow();
  runners.resume();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// A turn in progress is stopped (the tool with it) before the app goes, not left coding unwatched.
let stopped = false;
app.on("before-quit", (event) => {
  if (stopped || !runners.running) return;
  event.preventDefault();
  void runners.stopAll().finally(() => {
    stopped = true;
    app.quit();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
