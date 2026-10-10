// The only way out of a Docker coding sandbox (DOTRIX_CODING_SANDBOX=docker): an HTTPS proxy
// that tunnels CONNECTs to the hosts in DOTRIX_EGRESS_ALLOW ("api.anthropic.com:443,…") and
// refuses everything else. It runs in its own container, on the run's internal network (where
// the agent is) and on a network that reaches the internet; the agent's container has no route
// out but this. Each decision is logged as ALLOWED or DENIED.
import http from "node:http";
import net from "node:net";

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
  const upstream = net.connect(Number(port), host, () => {
    console.log(`ALLOWED ${target}`);
    client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
    if (head && head.length) upstream.write(head);
    upstream.pipe(client);
    client.pipe(upstream);
  });
  upstream.on("error", () => client.destroy());
  client.on("error", () => upstream.destroy());
});

server.listen(3128, "0.0.0.0", () => console.log(`egress proxy: ${[...allow].join(", ") || "nothing"} allowed`));
