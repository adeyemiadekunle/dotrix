// After `vite build` (the page) and `vite build --ssr` (its server render): the page's HTML written into
// dist/index.html, so dotrix.cc loads as static HTML (fast, and readable by search engines), then hydrates.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const template = fs.readFileSync(path.join(root, "dist/index.html"), "utf8");
const { render } = await import(pathToFileURL(path.join(root, "dist-ssr/entry-server.js")).href);
if (!template.includes("<!--app-->")) throw new Error("dist/index.html has no <!--app--> placeholder");
fs.writeFileSync(path.join(root, "dist/index.html"), template.replace("<!--app-->", render()));
fs.rmSync(path.join(root, "dist-ssr"), { recursive: true, force: true });
console.log("prerendered dist/index.html");
