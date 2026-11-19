// What a person types in the Browser pane's address bar, as a web address (or null when it isn't one).
// A dev server needs no scheme: `localhost:3000` and `127.0.0.1:5173` open on plain http; a site opens on https.

const SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i;
const LOCAL = /^(localhost|[a-z0-9-]+\.localhost|\d{1,3}(\.\d{1,3}){3}|\[[0-9a-f:]+\])$/i;

function parsed(url: string): string | null {
  try {
    const found = new URL(url);
    return found.protocol === "http:" || found.protocol === "https:" ? found.href : null;
  } catch {
    return null;
  }
}

export function toAddress(input: string): string | null {
  const text = input.trim();
  if (!text || /\s/.test(text)) return null;
  if (SCHEME.test(text)) return parsed(text);
  const authority = text.split(/[/?#]/, 1)[0]!;
  const host = authority.replace(/:\d+$/, "");
  const port = authority !== host;
  // A local name or address, or any host with a port (`devbox:3000`), is a dev server; a dotted name is a site.
  if (LOCAL.test(host) || (port && !host.includes("."))) return parsed(`http://${text}`);
  return host.includes(".") ? parsed(`https://${text}`) : null;
}

/** A tab's short name before its page has a title: the host, with its port. */
export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
