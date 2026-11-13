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
export function readSettings(raw: string | null): { keepCookies: boolean } {
  try {
    const saved = JSON.parse(raw ?? "") as { keepCookies?: unknown };
    return { keepCookies: saved.keepCookies === true };
  } catch {
    return { keepCookies: false };
  }
}
