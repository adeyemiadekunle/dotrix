// `virtual:icons`: exports only the Lucide icons (https://lucide.dev) that src/ names, as inline
// SVG markup, so the bundle carries the icons in use instead of the full set. Any quoted kebab-case
// token in src/ that is a Lucide icon, or a name in ALIASES, is included.
//
// The names src/ uses are dotrix's own (many came from Lucide, and projects store theirs in the
// database: PROJECT_ICONS), so ALIASES maps each that Lucide names differently to its glyph. A new
// icon can be named by its Lucide name directly.
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import type { Plugin } from "vite";

/** dotrix's icon names Lucide calls something else -> the Lucide icon. */
const ALIASES: Record<string, string> = {
  "arrow-circle-down": "circle-arrow-down",
  "arrow-clockwise": "rotate-cw",
  "arrow-square-out": "square-arrow-out-up-right",
  "arrows-in": "minimize-2",
  "arrows-out": "maximize-2",
  browser: "app-window",
  "chart-donut": "chart-pie",
  chat: "message-circle",
  "cursor-click": "mouse-pointer-click",
  desktop: "monitor",
  devices: "monitor-smartphone",
  "dots-three": "ellipsis",
  drop: "droplet",
  empty: "package-open",
  "file-c": "file-code",
  "file-c-sharp": "file-code",
  "file-cpp": "file-code",
  "file-css": "file-code",
  "file-csv": "file-spreadsheet",
  "file-html": "file-code",
  "file-js": "file-code",
  "file-jsx": "file-code",
  "file-md": "file-text",
  "file-pdf": "file-text",
  "file-py": "file-code",
  "file-rs": "file-code",
  "file-sql": "file-code",
  "file-svg": "file-image",
  "file-ts": "file-code",
  "file-tsx": "file-code",
  "file-txt": "file-text",
  "file-vue": "file-code",
  "file-zip": "file-archive",
  flask: "flask-conical",
  "flow-arrow": "workflow",
  "folder-simple": "folder",
  function: "square-function",
  gif: "file-image",
  graph: "chart-column",
  "hand-palm": "hand",
  "list-bullets": "list",
  "magnifying-glass": "search",
  "map-trifold": "map",
  note: "sticky-note",
  "pencil-simple": "pencil",
  "plus-minus": "diff",
  question: "circle-question-mark",
  queue: "list-todo",
  "sidebar-simple": "panel-left",
  "spinner-gap": "loader-circle",
  stack: "layers",
  "steering-wheel": "life-buoy",
  stop: "square",
  swatches: "palette",
  tabs: "panel-top",
  "terminal-window": "square-terminal",
  textbox: "text-cursor-input",
  tree: "network",
  "warning-circle": "circle-alert",
};

/** Brand icons Lucide no longer ships, as inner SVG markup (24-unit box, currentColor). */
const CUSTOM: Record<string, string> = {
  github:
    '<path fill="currentColor" stroke="none" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>',
};

const require = createRequire(import.meta.url);
// The package exports its SVGs by path only, so find the folder from one of them.
const LUCIDE = path.dirname(require.resolve("lucide-static/icons/check.svg"));

export function iconSubset(srcDir: string): Plugin {
  const id = "virtual:icons";
  const resolved = "\0" + id;
  const walk = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
      const p = path.join(dir, e.name);
      return e.isDirectory() ? walk(p) : /\.(ts|tsx)$/.test(e.name) ? [p] : [];
    });
  const file = (name: string) => path.join(LUCIDE, `${name}.svg`);
  return {
    name: "lucide-subset",
    resolveId: (s) => (s === id ? resolved : null),
    load(s) {
      if (s !== resolved) return null;
      const text = walk(srcDir)
        .map((f) => fs.readFileSync(f, "utf8"))
        .join("\n");
      const out: Record<string, string> = {};
      for (const [, name] of text.matchAll(/['"`]([a-z][a-z0-9]*(?:-[a-z0-9]+)*)['"`]/g)) {
        if (out[name!] !== undefined) continue;
        const glyph = CUSTOM[name!] ? name! : (ALIASES[name!] ?? name!);
        if (CUSTOM[glyph]) {
          out[name!] = CUSTOM[glyph]!;
          continue;
        }
        if (!fs.existsSync(file(glyph))) continue;
        // The elements inside the <svg> (a 24-unit box, stroked with currentColor; see Ic).
        out[name!] = fs
          .readFileSync(file(glyph), "utf8")
          .replace(/<!--[\s\S]*?-->/g, "")
          .trim()
          .replace(/^<svg[^>]*>/, "")
          .replace(/<\/svg>\s*$/, "")
          .trim();
      }
      return `export const ICONS = ${JSON.stringify(out)};`;
    },
    // A new icon name in a file: the module's list changes too.
    handleHotUpdate(ctx) {
      if (ctx.file.startsWith(srcDir.replaceAll("\\", "/")) || ctx.file.startsWith(srcDir)) {
        const mod = ctx.server.moduleGraph.getModuleById(resolved);
        if (mod) ctx.server.moduleGraph.invalidateModule(mod);
      }
    },
  };
}
