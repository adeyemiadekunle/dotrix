// Where the page sends people, set at build time (VITE_ variables; the defaults are production's).
const env = import.meta.env;

/** The cloud app (sign in, sign up). */
export const APP_URL = ((env.VITE_APP_URL as string | undefined) || "https://app.dotrix.cc").replace(/\/$/, "");
/** Public site canonical base URL. */
export const SITE_URL = ((env.VITE_SITE_URL as string | undefined) || "https://dotrix.cc").replace(/\/$/, "");
/** Component releases: desktop installers and standalone CLI archives have separate entries. */
export const DOWNLOADS_URL = (env.VITE_DOWNLOADS_URL as string | undefined) ?? "https://github.com/adeyemiadekunle/dotrix/releases";
/** Public beacon token for the consent-gated marketing analytics site. */
export const WEB_ANALYTICS_TOKEN = (env.VITE_CLOUDFLARE_WEB_ANALYTICS_TOKEN as string | undefined)?.trim();
