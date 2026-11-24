// After `vite build` (the page) and `vite build --ssr` (its server render): each route's HTML written into
// dist/, so dotrix.cc loads as static HTML (fast, and readable by search engines), then hydrates.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const SITE_URL = (process.env.VITE_SITE_URL || "https://dotrix.cc").replace(/\/$/, "");
const template = fs.readFileSync(path.join(root, "dist/index.html"), "utf8");
const { render } = await import(pathToFileURL(path.join(root, "dist-ssr/entry-server.js")).href);
if (!template.includes("<!--app-->")) throw new Error("dist/index.html has no <!--app--> placeholder");

const ROUTES = [
  { route: "/", out: "dist/index.html", title: null },
  { route: "/terms", out: "dist/terms/index.html", title: "Terms of Service · dotrix" },
  { route: "/privacy", out: "dist/privacy/index.html", title: "Privacy Policy · dotrix" },
];

for (const { route, out, title } of ROUTES) {
  const url = `${SITE_URL}${route === "/" ? "/" : route}`;
  let html = template
    .replace("<!--app-->", render(route))
    .replace('<link rel="canonical" href="https://dotrix.cc/" />', `<link rel="canonical" href="${url}" />`)
    .replace('<meta property="og:url" content="https://dotrix.cc/" />', `<meta property="og:url" content="${url}" />`)
    .replace('<meta property="og:image" content="https://dotrix.cc/og.png" />', `<meta property="og:image" content="${SITE_URL}/og.png" />`);
  if (title) {
    html = html
      .replace(/<title>[^<]*<\/title>/, `<title>${title}</title>`)
      .replace(/<meta property="og:title" content="[^"]*" \/>/, `<meta property="og:title" content="${title}" />`);
  }
  const dest = path.join(root, out);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, html);
  console.log(`prerendered ${out}`);
}

fs.rmSync(path.join(root, "dist-ssr"), { recursive: true, force: true });
