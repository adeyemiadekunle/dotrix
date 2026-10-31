// Packaging: record the address this release opens (DOTRIX_WEB_URL, an https:// origin) in dist/build.json,
// read by src/config.ts. Without DOTRIX_WEB_URL it refuses, so a release never opens localhost.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const value = process.env.DOTRIX_WEB_URL;
if (!value) {
  console.error("Set DOTRIX_WEB_URL to the address the app opens (e.g. https://dotrix.example.com)");
  process.exit(1);
}
let url;
try {
  url = new URL(value);
} catch {
  console.error(`DOTRIX_WEB_URL isn't an address: ${value}`);
  process.exit(1);
}
if (url.protocol !== "https:" && url.hostname !== "localhost") {
  console.error(`DOTRIX_WEB_URL must be https:// (got ${url.origin})`);
  process.exit(1);
}
const dist = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "dist");
fs.mkdirSync(dist, { recursive: true });
fs.writeFileSync(path.join(dist, "build.json"), JSON.stringify({ webUrl: url.origin }) + "\n");
console.log(`The app opens ${url.origin}`);
