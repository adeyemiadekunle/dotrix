// What the Browser pane may show, and which profile it uses. Pure, so node --test checks them.

/** The pane's profile kept on disk (cookies survive quitting the app). */
export const KEPT_PARTITION = "persist:dotrix-browser";
/** The pane's profile kept in memory only (gone when the app quits). */
export const CLEAN_PARTITION = "dotrix-browser";

/** The profile the pane uses: never the app's own, so a page there has none of dotrix's cookies. */
export function partitionFor(keepCookies: boolean): string {
  return keepCookies ? KEPT_PARTITION : CLEAN_PARTITION;
}

/** A page the pane may load: web pages only (a dev server on plain http included), never files or other schemes. */
export function browsable(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return parsed.protocol === "https:" || parsed.protocol === "http:";
}

/** The pane's saved settings, from whatever its file holds. */
export function readSettings(raw: string | null): { enabled: boolean; keepCookies: boolean; kaiAllowed: boolean } {
  try {
    const saved = JSON.parse(raw ?? "") as { enabled?: unknown; keepCookies?: unknown; kaiAllowed?: unknown };
    // The pane is there, and Kai may use it, unless a person turned that off.
    return { enabled: saved.enabled !== false, keepCookies: saved.keepCookies === true, kaiAllowed: saved.kaiAllowed !== false };
  } catch {
    return { enabled: true, keepCookies: false, kaiAllowed: true };
  }
}

/** An address on this computer (a dev server): the only pages Kai may open or act on. */
export function loopback(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
  const host = parsed.hostname;
  return host === "localhost" || host.endsWith(".localhost") || host === "[::1]" || /^127(\.\d{1,3}){3}$/.test(host);
}
