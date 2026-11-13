// The Browser pane beside a coding session (the web's components/BrowserPane.tsx): pages a person opens
// in the app, each tab a <webview> the app's page creates. Everything here keeps those pages apart from
// dotrix itself: a profile of their own (never the app's cookies), no preload and no Node, web addresses
// only, no permissions (camera, location, notifications…), no downloads, and links that ask for a new
// window become a new tab. A person chooses whether the profile's cookies outlive the app, and whether
// Kai may use the pane on a turn coding here (browserKai.ts: a tab of its own, pages on this computer only).
import { app, session, type Session, type WebContents, type WebPreferences } from "electron";
import fs from "node:fs";
import path from "node:path";

import { browsable, CLEAN_PARTITION, KEPT_PARTITION, loopback, partitionFor, readSettings } from "./browserRules";

export interface BrowserSettings {
  /** The pane is offered at all (Settings → Browser): off, no tab can be made and Kai has no browser. */
  enabled: boolean;
  keepCookies: boolean;
  /** Kai may open and act on pages of this computer's dev server in a tab of its own. */
  kaiAllowed: boolean;
  /** The profile a tab must use; a tab with another is refused. */
  partition: string;
}

export class Browser {
  private enabled: boolean;
  private keepCookies: boolean;
  private kaiAllowed: boolean;
  private readonly guarded = new Set<Session>();
  /** Whether a tab is Kai's (browserKai.ts): its pages stay on this computer. */
  kais: (tab: WebContents) => boolean = () => false;

  constructor(private readonly file = path.join(app.getPath("userData"), "browser.json")) {
    let raw: string | null = null;
    try {
      raw = fs.readFileSync(file, "utf8");
    } catch {
      // Never saved: a clean profile.
    }
    ({ enabled: this.enabled, keepCookies: this.keepCookies, kaiAllowed: this.kaiAllowed } = readSettings(raw));
  }

  private save(): void {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, JSON.stringify({ enabled: this.enabled, keepCookies: this.keepCookies, kaiAllowed: this.kaiAllowed }));
  }

  get settings(): BrowserSettings {
    return { enabled: this.enabled, keepCookies: this.keepCookies, kaiAllowed: this.kaiAllowed, partition: partitionFor(this.keepCookies) };
  }

  /** Keep the profile's cookies after the app quits, or not (what was kept is cleared). */
  async setKeepCookies(keep: boolean): Promise<BrowserSettings> {
    if (keep !== this.keepCookies) {
      this.keepCookies = keep;
      this.save();
      if (!keep) await wipe(session.fromPartition(KEPT_PARTITION));
    }
    return this.settings;
  }

  /** Turn the pane on or off for this computer (off: its open tabs go with the pane, and no new one can be made). */
  setEnabled(enabled: boolean): BrowserSettings {
    this.enabled = enabled;
    this.save();
    return this.settings;
  }

  /** Let Kai use the pane on a turn coding here, or not (its tools then say so). */
  setKaiAllowed(allowed: boolean): BrowserSettings {
    this.kaiAllowed = allowed;
    this.save();
    return this.settings;
  }

  /** Forget everything the pane's pages saved: cookies, storage, cache. */
  async clear(): Promise<void> {
    await Promise.all([wipe(session.fromPartition(KEPT_PARTITION)), wipe(session.fromPartition(CLEAN_PARTITION))]);
  }

  /** A tab the app's page is about to create: forced into the pane's profile, with nothing of the app's. False refuses it. */
  attach(webPreferences: WebPreferences, params: Record<string, string>): boolean {
    if (!this.enabled || (params.src && !browsable(params.src))) return false;
    const partition = this.settings.partition;
    delete webPreferences.preload;
    webPreferences.nodeIntegration = false;
    webPreferences.nodeIntegrationInSubFrames = false;
    webPreferences.contextIsolation = true;
    webPreferences.sandbox = true;
    webPreferences.webSecurity = true;
    webPreferences.partition = partition;
    params.partition = partition;
    this.guard(session.fromPartition(partition));
    return true;
  }

  /** A tab that exists: it stays on web pages, and a new window it asks for is offered to the app's page as a tab. */
  watch(tab: WebContents): void {
    const stay = (event: { preventDefault(): void }, url: string): void => {
      if (!browsable(url) || (this.kais(tab) && !loopback(url))) event.preventDefault();
    };
    tab.on("will-navigate", stay);
    tab.on("will-redirect", stay);
    tab.setWindowOpenHandler(({ url }) => {
      const host = tab.hostWebContents;
      // From Kai's tab, only this computer's pages open (as an ordinary tab).
      if (browsable(url) && (!this.kais(tab) || loopback(url)) && host && !host.isDestroyed()) host.send("dotrix:browser:open", url);
      return { action: "deny" };
    });
  }

  private guard(profile: Session): void {
    if (this.guarded.has(profile)) return;
    this.guarded.add(profile);
    profile.setPermissionRequestHandler((_contents, _permission, answer) => answer(false));
    profile.setPermissionCheckHandler(() => false);
    profile.on("will-download", (event) => event.preventDefault());
  }
}

async function wipe(profile: Session): Promise<void> {
  await profile.clearStorageData();
  await profile.clearCache();
}
