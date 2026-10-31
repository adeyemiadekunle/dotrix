// `virtual:icons`: exports only the Phosphor icons (regular weight, https://phosphoricons.com) that src/
// names, as inline SVG markup, so the bundle carries the icons in use instead of the full set. Any
// quoted kebab-case token in src/ that is a Phosphor icon, or a name in ALIASES, is included.
//
// The names src/ uses are dotrix's own (many came from Lucide, and projects store theirs in the
// database: PROJECT_ICONS), so ALIASES maps each that Phosphor names differently to its glyph. A new
// icon can be named by its Phosphor name directly.
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import type { Plugin } from "vite";

/** dotrix's icon names Phosphor calls something else -> the Phosphor icon. */
const ALIASES: Record<string, string> = {
  activity: "pulse",
  "arrow-down-wide-narrow": "sort-descending",
  "arrow-left-right": "arrows-left-right",
  "arrow-up-down": "arrows-down-up",
  "at-sign": "at",
  badge: "seal",
  baseline: "text-underline",
  bold: "text-b",
  bot: "robot",
  box: "cube",
  "building-2": "buildings",
  "calendar-arrow-up": "calendar-check",
  "calendar-days": "calendar-dots",
  "check-check": "checks",
  "chevron-down": "caret-down",
  "chevron-left": "caret-left",
  "chevron-right": "caret-right",
  "chevron-up": "caret-up",
  "chevrons-up-down": "caret-up-down",
  "circle-alert": "warning-circle",
  "circle-check": "check-circle",
  "circle-dot": "radio-button",
  "circle-help": "question",
  "circle-plus": "plus-circle",
  "circle-x": "x-circle",
  "clock-alert": "clock-countdown",
  "cloud-alert": "cloud-warning",
  "columns-3": "columns",
  component: "diamonds-four",
  "corner-down-right": "arrow-elbow-down-right",
  diff: "git-diff",
  ellipsis: "dots-three",
  "ellipsis-vertical": "dots-three-vertical",
  "external-link": "arrow-square-out",
  "file-clock": "clock-counter-clockwise",
  "file-pen": "note-pencil",
  "file-question": "file-dashed",
  "file-spreadsheet": "file-xls",
  filter: "funnel",
  "flask-conical": "flask",
  "fold-horizontal": "arrows-in-line-horizontal",
  "folder-archive": "archive",
  "folder-git-2": "folder-simple-star",
  "folder-input": "folder-open",
  "folder-kanban": "kanban",
  "folder-tree": "tree-structure",
  form: "textbox",
  "git-commit-horizontal": "git-commit",
  "git-compare": "git-diff",
  github: "github-logo",
  grid: "grid-four",
  "grip-vertical": "dots-six-vertical",
  group: "selection-all",
  heading: "text-h",
  history: "clock-counter-clockwise",
  home: "house",
  inbox: "tray",
  italic: "text-italic",
  "key-round": "key",
  layers: "stack",
  "layout-dashboard": "squares-four",
  "layout-grid": "grid-four",
  "list-filter": "funnel-simple",
  "list-ordered": "list-numbers",
  "list-tree": "tree-view",
  "log-out": "sign-out",
  mail: "envelope-simple",
  "mail-open": "envelope-simple-open",
  map: "map-trifold",
  "maximize-2": "arrows-out-simple",
  menu: "list",
  "message-square": "chat-centered",
  "message-square-plus": "chat-centered-dots",
  "minimize-2": "arrows-in-simple",
  "monitor-smartphone": "devices",
  move: "arrows-out-cardinal",
  "panel-left": "sidebar-simple",
  "panel-left-close": "sidebar-simple",
  "panel-left-open": "sidebar-simple",
  "panel-right-close": "sidebar",
  "panel-right-open": "sidebar",
  "pen-tool": "pen-nib",
  pin: "push-pin",
  "pin-off": "push-pin-slash",
  pointer: "cursor",
  "refresh-cw": "arrows-clockwise",
  replace: "swap",
  rose: "flower",
  "rotate-ccw": "arrow-counter-clockwise",
  "rows-3": "rows",
  "scroll-text": "scroll",
  search: "magnifying-glass",
  "search-check": "magnifying-glass",
  "search-x": "magnifying-glass-minus",
  send: "paper-plane-tilt",
  settings: "gear",
  "settings-2": "gear-six",
  "share-2": "share-network",
  sheet: "table",
  "signal-high": "cell-signal-high",
  smartphone: "device-mobile",
  "smile-plus": "smiley",
  sparkles: "sparkle",
  "square-check": "check-square",
  "square-kanban": "kanban",
  "square-pen": "note-pencil",
  "square-terminal": "terminal-window",
  summary: "article",
  "table-2": "table",
  text: "text-align-left",
  timeline: "chart-bar-horizontal",
  "trash-2": "trash",
  "triangle-alert": "warning",
  type: "text-t",
  "undo-2": "arrow-u-up-left",
  "upload-cloud": "cloud-arrow-up",
  view: "eye",
  wifi: "wifi-high",
  "wifi-off": "wifi-slash",
  zap: "lightning",
};

const require = createRequire(import.meta.url);
// The package exports its SVGs by path only, so find the folder from one of them.
const PHOSPHOR = path.dirname(require.resolve("@phosphor-icons/core/regular/house.svg"));

export function iconSubset(srcDir: string): Plugin {
  const id = "virtual:icons";
  const resolved = "\0" + id;
  const walk = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
      const p = path.join(dir, e.name);
      return e.isDirectory() ? walk(p) : /\.(ts|tsx)$/.test(e.name) ? [p] : [];
    });
  const file = (name: string) => path.join(PHOSPHOR, `${name}.svg`);
  return {
    name: "phosphor-subset",
    resolveId: (s) => (s === id ? resolved : null),
    load(s) {
      if (s !== resolved) return null;
      const text = walk(srcDir)
        .map((f) => fs.readFileSync(f, "utf8"))
        .join("\n");
      const out: Record<string, string> = {};
      for (const [, name] of text.matchAll(/['"`]([a-z][a-z0-9]*(?:-[a-z0-9]+)*)['"`]/g)) {
        if (out[name!] !== undefined) continue;
        const glyph = ALIASES[name!] ?? name!;
        if (!fs.existsSync(file(glyph))) continue;
        // The paths inside the <svg> (a 256-unit box, filled with currentColor; see Ic).
        out[name!] = fs
          .readFileSync(file(glyph), "utf8")
          .replace(/^<svg[^>]*>/, "")
          .replace(/<\/svg>\s*$/, "");
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
