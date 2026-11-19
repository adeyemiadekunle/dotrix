// System notifications for what waits on a person (an approval, a run stopped at its limit), asked
// for by the app's own page (main.ts checks the sender). Only text is shown; what a click or a
// button means goes back to that page, which makes the decision through the API as its notice
// does, so this process never decides anything or holds a token. Buttons are macOS only (Electron
// shows them nowhere else); elsewhere a click brings the app forward to the item.
import { BrowserWindow, Notification, type WebContents } from "electron";

interface Shown {
  id: string;
  title: string;
  body: string;
  actions: string[];
}

const live = new Map<string, Notification>(); // kept referenced, or a click may never arrive

function text(value: unknown, max: number): string {
  return typeof value === "string" ? value.slice(0, max) : "";
}

function parse(value: unknown): Shown | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const id = text(raw.id, 200);
  const title = text(raw.title, 120);
  if (!id || !title) return null;
  const actions = Array.isArray(raw.actions)
    ? raw.actions
        .map((a) => text(a, 24))
        .filter(Boolean)
        .slice(0, 2)
    : [];
  return { id, title, body: text(raw.body, 240), actions };
}

export function notify(page: WebContents, value: unknown): boolean {
  const shown = parse(value);
  if (!shown || !Notification.isSupported() || live.has(shown.id)) return false;
  const actions = process.platform === "darwin" ? shown.actions : [];
  const n = new Notification({
    title: shown.title,
    body: shown.body,
    actions: actions.map((label) => ({ type: "button" as const, text: label })),
  });
  const send = (action: string | null) => {
    if (!page.isDestroyed()) page.send("dotrix:notify", shown.id, action);
  };
  n.on("click", () => {
    const win = BrowserWindow.fromWebContents(page);
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
    send(null);
  });
  n.on("action", (_event, index) => send(actions[index] ?? null));
  n.on("close", () => live.delete(shown.id));
  live.set(shown.id, n);
  n.show();
  return true;
}
