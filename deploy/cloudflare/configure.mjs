import { readFile, writeFile } from "node:fs/promises";

const [account, digest] = process.argv.slice(2);
if (!/^[a-f0-9]{32}$/.test(account ?? "") || !/^sha256:[a-f0-9]{64}$/.test(digest ?? "")) {
  throw new Error("Usage: node deploy/cloudflare/configure.mjs <Cloudflare account ID> <Cloudflare image digest>");
}

const hostname = "cf-pilot.dotrix.cc";
const config = JSON.parse(await readFile(new URL("wrangler.template.json", import.meta.url), "utf8"));
config.account_id = account;
config.vars = { DOTRIX_APP_URL: `https://${hostname}` };
config.routes = [{ pattern: hostname, custom_domain: true }];
config.containers[0].images.base = { image: `registry.cloudflare.com/${account}/dotrix-backend@${digest}` };
await writeFile(new URL("wrangler.generated.json", import.meta.url), JSON.stringify(config, null, 2) + "\n");
