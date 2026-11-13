// The desktop app's bridge (apps/desktop: preload.ts), when the web app runs inside it: its runners
// (the bundled dotrix CLI's `dotrix runner`, one per folder a person picks), the live worktrees of
// the turns they code, the app's version and What's new, and its updates. In a browser there's none,
// and every helper here says so; an older app has runners and worktrees but no updates.
import { useEffect, useState, useSyncExternalStore } from "react";

import type { CodingRun } from "@/lib/coding";

export interface DesktopRunner {
  folder: string;
  workspace: string;
  projectKey: string;
  state: "starting" | "waiting" | "coding" | "stopped" | "failed";
  runnerId?: string;
  name?: string;
  isolation?: string;
  tools?: string[];
  turn?: { runId: string; issueKey: string; turn: number; worktree: string };
  message?: string;
}

interface WorktreeTree {
  entries: { path: string; status: "added" | "modified" | "deleted" | "unchanged"; size: number | null }[];
  truncated: boolean;
}

interface WorktreeFile {
  path: string;
  status: "added" | "modified" | "deleted" | "unchanged";
  before: string | null;
  after: string | null;
  binary: boolean;
  too_large: boolean;
}

/** A release in the app's bundled CHANGELOG.md. */
export interface DesktopRelease {
  version: string;
  date: string | null;
  sections: { title: string; items: string[] }[];
}

export type DesktopUpdate =
  | { state: "off" }
  | { state: "idle"; checked: string | null }
  | { state: "checking" }
  | { state: "downloading"; version: string; percent: number }
  | { state: "ready"; version: string }
  | { state: "failed"; message: string };

interface AppBridge {
  app: {
    info(): Promise<{ version: string; platform: string; packaged: boolean }>;
    changelog(): Promise<DesktopRelease[]>;
  };
  updates: {
    state(): Promise<DesktopUpdate>;
    check(): Promise<DesktopUpdate>;
    install(): Promise<void>;
    onChange(listener: (state: DesktopUpdate) => void): () => void;
  };
}

interface Bridge {
  platform: string;
  runners: {
    list(): Promise<DesktopRunner[]>;
    add(workspace: string, projectKey: string): Promise<DesktopRunner | null>;
    remove(folder: string): Promise<void>;
    restart(folder: string): Promise<void>;
    signIn(): Promise<void>;
    onChange(listener: (runners: DesktopRunner[]) => void): () => void;
  };
  worktree: {
    tree(worktree: string): Promise<WorktreeTree>;
    file(worktree: string, file: string): Promise<WorktreeFile>;
    open(worktree: string): Promise<void>;
    reveal(worktree: string): Promise<void>;
  };
}

/** The desktop app's bridge, or null in a browser (or an older app without runners). */
export function desktop(): Bridge | null {
  const found = (globalThis as { dotrixDesktop?: Partial<Bridge> }).dotrixDesktop;
  return found?.runners && found.worktree ? (found as Bridge) : null;
}

interface NotifyBridge {
  notify: {
    supported(): Promise<boolean>;
    show(notice: { id: string; title: string; body: string; actions: string[] }): Promise<boolean>;
    /** A click (action null) or a button (its label, macOS only) on a notification this page showed. */
    onAction(listener: (id: string, action: string | null) => void): () => void;
  };
}

/** The app's system notifications, or null in a browser or an app from before them. */
export function desktopNotify(): NotifyBridge["notify"] | null {
  return (globalThis as { dotrixDesktop?: Partial<NotifyBridge> }).dotrixDesktop?.notify ?? null;
}

export interface BrowserSettings {
  /** The pane is offered at all on this computer (Settings → Browser). */
  enabled: boolean;
  keepCookies: boolean;
  /** Kai may use the pane (a tab of its own, pages on this computer only) on a turn coding here. */
  kaiAllowed: boolean;
  /** The profile every tab uses: the app refuses a tab with another. */
  partition: string;
}

export interface KaiTabRequest {
  id: number;
  url: string;
}

interface BrowserBridge {
  browser: {
    settings(): Promise<BrowserSettings>;
    setKeepCookies(keep: boolean): Promise<BrowserSettings>;
    clear(): Promise<void>;
    /** A page in the pane asked for a new window: open it as a tab. */
    onOpen(listener: (url: string) => void): () => void;
    setEnabled(enabled: boolean): Promise<BrowserSettings>;
    setKaiAllowed(allowed: boolean): Promise<BrowserSettings>;
    /** Kai, coding on this computer, asks for its tab at an address there: the pane opens and makes it. */
    onKai(listener: (request: KaiTabRequest) => void): () => void;
    /** The request still waiting, for a pane that opened after it was sent. */
    kaiRequest(): Promise<KaiTabRequest | null>;
    /** Which page the pane made for a request (the app checks it before Kai may use it). */
    kaiReady(id: number, contentsId: number): Promise<void>;
  };
}

/** The app's Browser pane (its profile and settings), or null in a browser or an app from before it. */
export function desktopBrowser(): BrowserBridge["browser"] | null {
  return (globalThis as { dotrixDesktop?: Partial<BrowserBridge> }).dotrixDesktop?.browser ?? null;
}

// The pane's settings, shared by everything that shows them (the pane, its menu, Settings → Browser, Codes' list of panes).
let browserSettings: BrowserSettings | null = null;
let browserAsked = false;
const browserWatchers = new Set<() => void>();

/** What a change to the pane's settings answered: everything showing them follows. */
export function setBrowserSettings(next: BrowserSettings): void {
  browserSettings = next;
  for (const watcher of browserWatchers) watcher();
}

/** The Browser pane's settings on this computer, kept current (null in a browser, and until the app answers). */
export function useBrowserSettings(): BrowserSettings | null {
  return useSyncExternalStore(
    (watcher) => {
      browserWatchers.add(watcher);
      if (!browserAsked) {
        browserAsked = true;
        void desktopBrowser()?.settings().then(setBrowserSettings);
      }
      return () => browserWatchers.delete(watcher);
    },
    () => browserSettings,
  );
}

/** The app's version, What's new and updates, or null in a browser or an app from before them. */
export function desktopApp(): AppBridge | null {
  const found = (globalThis as { dotrixDesktop?: Partial<AppBridge> }).dotrixDesktop;
  return found?.app && found.updates ? (found as AppBridge) : null;
}

/** The app's update, kept current (null in a browser). */
export function useDesktopUpdate(): DesktopUpdate | null {
  const [state, setState] = useState<DesktopUpdate | null>(null);
  useEffect(() => {
    const bridge = desktopApp();
    if (!bridge) return;
    let live = true;
    void bridge.updates.state().then((s) => live && setState(s));
    const off = bridge.updates.onChange(setState);
    return () => {
      live = false;
      off();
    };
  }, []);
  return state;
}

/** This computer's runners, kept current (empty in a browser). */
export function useDesktopRunners(): DesktopRunner[] {
  const [runners, setRunners] = useState<DesktopRunner[]>([]);
  useEffect(() => {
    const bridge = desktop();
    if (!bridge) return;
    let live = true;
    void bridge.runners.list().then((list) => live && setRunners(list));
    const off = bridge.runners.onChange(setRunners);
    return () => {
      live = false;
      off();
    };
  }, []);
  return runners;
}

/** A local turn's worktree when it's on this computer (one of its runners claimed it), else null. */
export function worktreeHere(run: Pick<CodingRun, "location" | "runner_id" | "worktree"> | undefined, runners: DesktopRunner[]): string | null {
  if (!run || run.location !== "local" || !run.worktree || !run.runner_id || !desktop()) return null;
  return runners.some((r) => r.runnerId === run.runner_id) ? run.worktree : null;
}
