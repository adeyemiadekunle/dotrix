// Where the page sends people, set at build time (VITE_ variables; the defaults are production's).
const env = import.meta.env;

/** The cloud app (sign in, sign up). */
export const APP_URL = (env.VITE_APP_URL as string | undefined) ?? "https://app.dotrix.cc";
/** The releases page: the Windows installer and the standalone CLI are attached to each release. */
export const DOWNLOADS_URL = (env.VITE_DOWNLOADS_URL as string | undefined) ?? "https://github.com/adeyemiadekunle/dotrix/releases/latest";
