// Gr8r's `virtual:icons` (gr8r-studio/vite.config.js): exports only the Lucide icons src/ names, as
// inline SVG markup, so the bundle carries the icons in use instead of the full set. Any quoted
// kebab-case token in src/ that matches a Lucide icon name is included.
import fs from "node:fs";
import path from "node:path";

import { icons as lucide } from "lucide";
import type { Plugin } from "vite";

type Node = [string, Record<string, string | number>][];

export function lucideSubset(srcDir: string): Plugin {
  const id = "virtual:icons";
  const resolved = "\0" + id;
  const walk = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
      const p = path.join(dir, e.name);
      return e.isDirectory() ? walk(p) : /\.(ts|tsx)$/.test(e.name) ? [p] : [];
    });
  const pascal = (n: string) =>
    n
      .split("-")
      .map((p) => p[0]!.toUpperCase() + p.slice(1))
      .join("");
  const table = lucide as unknown as Record<string, Node | ["svg", unknown, Node]>;
  return {
    name: "lucide-subset",
    resolveId: (s) => (s === id ? resolved : null),
    load(s) {
      if (s !== resolved) return null;
      const text = walk(srcDir)
        .map((f) => fs.readFileSync(f, "utf8"))
        .join("\n");
      const names = [...new Set([...text.matchAll(/['"`]([a-z][a-z0-9]*(?:-[a-z0-9]+)*)['"`]/g)].map((m) => m[1]!))].filter((n) => table[pascal(n)]).sort();
      const out: Record<string, string> = {};
      for (const n of names) {
        let node = table[pascal(n)]!;
        if (node[0] === "svg") node = (node as ["svg", unknown, Node])[2];
        out[n] = (node as Node)
          .map(
            ([t, a]) =>
              `<${t} ${Object.entries(a)
                .filter(([k]) => k !== "key")
                .map(([k, v]) => `${k}="${v}"`)
                .join(" ")}/>`,
          )
          .join("");
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
