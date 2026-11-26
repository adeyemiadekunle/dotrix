// Where the app opens. Developing: DOTRIX_WEB_URL, else the local dev server. A release: the address it
// was built for, in build.json beside this file (scripts/build-config.mjs writes it when packaging).
import fs from "node:fs";
import path from "node:path";

const DEV_SERVER = "http://localhost:3000";

function buildConfig(): { webUrl?: unknown; staging?: unknown } {
  try {
    return JSON.parse(fs.readFileSync(path.join(__dirname, "build.json"), "utf8"));
  } catch {
    return {};
  }
}

const build = buildConfig();
export const webUrl = () => process.env.DOTRIX_WEB_URL || (typeof build.webUrl === "string" && build.webUrl) || DEV_SERVER;
export const stagingBuild = () => build.staging === true;
