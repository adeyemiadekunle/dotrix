// Updates: a release build checks GitHub Releases (electron-updater, the `publish` settings in
// package.json) when it starts and every few hours, downloads a new version in the background, and tells
// the web app, which shows "dotrix X is ready" with Restart. Not restarting installs it when the app quits.
// Development builds never check.
import { app, BrowserWindow } from "electron";
import { autoUpdater, type UpdateInfo } from "electron-updater";

export type UpdateState =
  | { state: "off" } // a development build
  | { state: "idle"; checked: string | null } // up to date, as of when it last checked
  | { state: "checking" }
  | { state: "downloading"; version: string; percent: number }
  | { state: "ready"; version: string }
  | { state: "failed"; message: string };

const EVERY_MS = 4 * 60 * 60 * 1000;

export class Updates {
  private current: UpdateState = { state: "off" };
  private timer: NodeJS.Timeout | null = null;

  constructor(private beforeInstall: () => Promise<void>) {}

  get state(): UpdateState {
    return this.current;
  }

  private set(next: UpdateState): void {
    this.current = next;
    for (const win of BrowserWindow.getAllWindows()) win.webContents.send("dotrix:updates", next);
  }

  start(): void {
    if (!app.isPackaged) return;
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = true;
    autoUpdater.allowPrerelease = false;
    autoUpdater.logger = null;
    autoUpdater.on("checking-for-update", () => {
      if (this.current.state !== "ready" && this.current.state !== "downloading") this.set({ state: "checking" });
    });
    autoUpdater.on("update-not-available", () => this.set({ state: "idle", checked: new Date().toISOString() }));
    autoUpdater.on("update-available", (info: UpdateInfo) => this.set({ state: "downloading", version: info.version, percent: 0 }));
    autoUpdater.on("download-progress", (p) => {
      if (this.current.state === "downloading") this.set({ ...this.current, percent: Math.round(p.percent) });
    });
    autoUpdater.on("update-downloaded", (info: UpdateInfo) => this.set({ state: "ready", version: info.version }));
    autoUpdater.on("error", (error: Error) => {
      // A failed check isn't worth a banner: it tries again later. Only say so when asked to check.
      if (this.current.state !== "ready") this.set({ state: "failed", message: error.message.split("\n")[0]!.slice(0, 200) });
    });
    void this.check();
    this.timer = setInterval(() => void this.check(), EVERY_MS);
  }

  async check(): Promise<UpdateState> {
    if (!app.isPackaged || this.current.state === "ready" || this.current.state === "downloading") return this.current;
    try {
      await autoUpdater.checkForUpdates();
    } catch {
      // reported through the "error" event
    }
    return this.current;
  }

  /** Restart into the downloaded version: stop any local turn first (beforeInstall), then install. */
  async install(): Promise<void> {
    if (this.current.state !== "ready") throw new Error("No update is ready to install");
    if (this.timer) clearInterval(this.timer);
    await this.beforeInstall();
    setImmediate(() => autoUpdater.quitAndInstall(false, true));
  }
}
