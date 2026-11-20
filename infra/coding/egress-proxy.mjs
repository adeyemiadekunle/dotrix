// The only way out of a Docker coding sandbox (DOTRIX_CODING_SANDBOX=docker): an HTTPS proxy
// that tunnels CONNECTs to the hosts in DOTRIX_EGRESS_ALLOW ("api.anthropic.com:443,…") and
// refuses everything else. It runs in its own container, on the run's internal network (where
// the agent is) and on a network that reaches the internet; the agent's container has no route
// out but this. Each decision is logged as ALLOWED or DENIED.
//
// DOTRIX_EGRESS_DNS ("1.1.1.1,8.8.8.8") names the resolvers it looks the allowed hosts up with. Under gVisor
// a container on a user-defined network can't reach Docker's resolver (127.0.0.11), so the sandbox passes
// them there; unset, the system resolver answers.
import { Resolver } from "node:dns/promises";
import http from "node:http";
import net from "node:net";

const servers = (process.env.DOTRIX_EGRESS_DNS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const resolver = servers.length ? new Resolver({ timeout: 5_000, tries: 2 }) : null;
if (resolver) resolver.setServers(servers);
/** The address to connect to: the host itself, or one of its addresses from the named resolvers. */
async function address(host) {
  if (!resolver || net.isIP(host)) return host;
  const found = await resolver.resolve4(host).catch(() => resolver.resolve6(host));
  if (!found.length) throw new Error(`no address for ${host}`);
  return found[0];
}

const allow = new Set(
  (process.env.DOTRIX_EGRESS_ALLOW || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean),
);

const server = http.createServer((req, res) => {
  console.log(`DENIED ${req.method} ${req.url}`);
  res.writeHead(403, { "content-type": "text/plain" });
  res.end("dotrix sandbox: only HTTPS to the model API is allowed\n");
});

server.on("connect", (req, client, head) => {
  const target = String(req.url || "").toLowerCase();
  const [host, port] = target.split(":");
  if (!allow.has(target) || !host || !port) {
    console.log(`DENIED ${target}`);
    client.end("HTTP/1.1 403 Forbidden\r\n\r\n");
    return;
  }
  let upstream = null;
  client.on("error", () => upstream?.destroy());
  address(host).then(
    (ip) => {
      upstream = net.connect(Number(port), ip, () => {
        console.log(`ALLOWED ${target}`);
        client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
        if (head && head.length) upstream.write(head);
        upstream.pipe(client);
        client.pipe(upstream);
      });
      upstream.on("error", () => client.destroy());
    },
    () => {
      console.log(`UNRESOLVED ${target}`);
      client.end("HTTP/1.1 502 Bad Gateway\r\n\r\n");
    },
  );
});

server.listen(3128, "0.0.0.0", () => console.log(`egress proxy: ${[...allow].join(", ") || "nothing"} allowed`));
