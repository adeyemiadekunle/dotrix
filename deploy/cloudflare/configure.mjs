import { readFile, writeFile } from "node:fs/promises";

const [account, digest, revision] = process.argv.slice(2);
if (!/^[a-f0-9]{32}$/.test(account ?? "") || !/^sha256:[a-f0-9]{64}$/.test(digest ?? "") || !/^[a-f0-9]{40}$/.test(revision ?? "")) {
  throw new Error("Usage: node deploy/cloudflare/configure.mjs <Cloudflare account ID> <Cloudflare image digest> <Git commit SHA>");
}

const config = JSON.parse(await readFile(new URL("wrangler.template.json", import.meta.url), "utf8"));
config.account_id = account;
config.routes = Object.values(config.vars).map((url) => ({ pattern: new URL(url).hostname, custom_domain: true }));
config.vars.DOTRIX_DEPLOYMENT_REVISION = revision;
config.containers[0].images.base = { image: `registry.cloudflare.com/${account}/dotrix-backend@${digest}` };
await writeFile(new URL("wrangler.generated.json", import.meta.url), JSON.stringify(config, null, 2) + "\n");
