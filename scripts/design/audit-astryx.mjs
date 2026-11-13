// Keep every published documentation entry visible when the pinned library changes.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");
const source = join(root, "packages/ui/node_modules/@astryxdesign/core/src");
function docs(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((item) =>
    item.isDirectory() ? docs(join(dir, item.name)) : item.name.endsWith(".doc.mjs") ? [join(dir, item.name)] : [],
  );
}
const entries = docs(source).map((file) => ({
  name: readFileSync(file, "utf8").match(/export const docs = \{\s*name: '([^']+)'/)?.[1] ?? file.split("/").at(-1).replace(".doc.mjs", ""),
  file: relative(source, file),
}));
const ledger = readFileSync(join(root, "docs/astryx-migration.md"), "utf8");
const missing = entries.filter(({ file }) => !ledger.includes(`\`${file}\``));
const packageJson = JSON.parse(readFileSync(join(source, "../package.json"), "utf8"));
if (!ledger.includes(`Version: **${packageJson.version}**`) || missing.length) {
  console.error("Astryx inventory needs review:", missing.map(({ name }) => name).join(", ") || "version changed");
  process.exitCode = 1;
} else console.log(`Astryx ${packageJson.version}: all ${entries.length} published documentation entries have a disposition.`);
