// Which links the desktop app hands to the system, and which pages its window may show. Pure, so node --test checks them.

/** A link the system may open: web pages (plain http only for a local server in development) and email. */
export function opensOutside(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol === "https:" || parsed.protocol === "mailto:") return true;
  return parsed.protocol === "http:" && (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1");
}

// The pages on github.com the app's own redirects pass through:
//  - sign in: /api/auth/github redirects to https://github.com/login/oauth/authorize (modules/auth/github.py `AUTHORIZE_URL`);
//    GitHub sends a signed-out person to /login, and to /sessions/... for two-factor and device checks along the way.
//  - install the App: /api/github/install redirects to https://github.com/apps/<slug>/installations/new (modules/connectors/github_app.py
//    `install_url`, checked by `INSTALL_URL` in modules/web/router.py), which continues on /apps/ and /settings/installations/...
//    before GitHub returns to /api/github/setup on the app's own origin.
const GITHUB_PATHS = ["/login", "/sessions", "/apps", "/settings/installations"];

function onPath(path: string, prefix: string): boolean {
  return path === prefix || path.startsWith(`${prefix}/`);
}

/** A page the app's window may load: the app's own origin, or GitHub's sign-in and install pages its redirects use. */
export function staysInside(url: string, appUrl: string): boolean {
  let parsed: URL;
  let app: URL;
  try {
    parsed = new URL(url);
    app = new URL(appUrl);
  } catch {
    return false;
  }
  if (parsed.origin === app.origin) return true;
  return parsed.protocol === "https:" && parsed.hostname === "github.com" && !parsed.port && GITHUB_PATHS.some((prefix) => onPath(parsed.pathname, prefix));
}
