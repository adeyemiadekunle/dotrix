import { execFileSync } from "node:child_process";
import { cp, mkdir, readFile, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../..", import.meta.url));
const { vars } = JSON.parse(await readFile(new URL("wrangler.template.json", import.meta.url), "utf8"));
const env = { ...process.env, VITE_APP_URL: vars.DOTRIX_APP_URL, VITE_SITE_URL: vars.DOTRIX_SITE_URL };
for (const name of ["web", "admin", "site"]) {
  execFileSync("pnpm", [`build:${name}`], { cwd: root, env, stdio: "inherit" });
}

const assets = new URL("./dist/", import.meta.url);
await rm(assets, { recursive: true, force: true });
await mkdir(assets, { recursive: true });
for (const name of ["web", "admin", "site"]) {
  await cp(new URL(`../../apps/${name}/dist/`, import.meta.url), new URL(`_${name}/`, assets), { recursive: true });
}
