// Where the app opens. Developing: DOTRIX_WEB_URL, else the local dev server. A release: the address it
// was built for, in build.json beside this file (scripts/build-config.mjs writes it when packaging).
import fs from "node:fs";
import path from "node:path";

const DEV_SERVER = "http://localhost:3000";

export function webUrl(): string {
  if (process.env.DOTRIX_WEB_URL) return process.env.DOTRIX_WEB_URL;
  try {
    const built = JSON.parse(fs.readFileSync(path.join(__dirname, "build.json"), "utf8")) as { webUrl?: unknown };
    if (typeof built.webUrl === "string" && built.webUrl) return built.webUrl;
  } catch {
    // Not a release build: the dev server.
  }
  return DEV_SERVER;
}
