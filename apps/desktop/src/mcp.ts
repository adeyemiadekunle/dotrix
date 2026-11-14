// A small MCP server (Streamable HTTP, JSON answers) for the tools the app offers Kai on a local turn:
// today, the Browser pane's (browserKai.ts). It listens on this computer only, on a port of its own, and
// answers only requests that carry a token it gave out (one per caller: each runner, made anew each time the
// app starts), so another program here can't use it by finding the port, and a web page can't at all (a request
// with an Origin is refused). The token also says who is calling, so a tool knows whose turn it acts for.
import crypto from "node:crypto";
import http from "node:http";
import type { AddressInfo } from "node:net";

export type Content = { type: "text"; text: string } | { type: "image"; data: string; mimeType: string };

export interface Tool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface ToolSet {
  /** The tools this caller is offered now. */
  list(caller: string): Tool[];
  /** The tool's answer; a thrown Error is told to the agent as the tool's failure. */
  call(name: string, args: Record<string, unknown>, caller: string): Promise<Content[]>;
}

const PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"];
const MAX_BODY = 1_000_000;

interface Rpc {
  jsonrpc?: string;
  id?: string | number | null;
  method?: string;
  params?: Record<string, unknown>;
}

export class McpServer {
  private readonly callers = new Map<string, string>(); // token -> caller
  private readonly tokens = new Map<string, string>(); // caller -> token
  private server: http.Server | null = null;
  private port = 0;

  constructor(
    private readonly name: string,
    private readonly version: string,
    private readonly tools: ToolSet,
  ) {}

  /** Where it listens, once started. */
  get url(): string | null {
    return this.port ? `http://127.0.0.1:${this.port}/mcp` : null;
  }

  /** The token a caller (a runner's folder) uses: the same one for it while the app runs. */
  tokenFor(caller: string): string {
    let token = this.tokens.get(caller);
    if (!token) {
      token = crypto.randomBytes(32).toString("hex");
      this.tokens.set(caller, token);
      this.callers.set(token, caller);
    }
    return token;
  }

  async start(): Promise<void> {
    const server = http.createServer((request, response) => void this.handle(request, response));
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    this.server = server;
    this.port = (server.address() as AddressInfo).port;
  }

  stop(): void {
    this.server?.close();
    this.server = null;
    this.port = 0;
  }

  private async handle(request: http.IncomingMessage, response: http.ServerResponse): Promise<void> {
    const send = (status: number, body?: unknown): void => {
      response.writeHead(status, body === undefined ? {} : { "content-type": "application/json" });
      response.end(body === undefined ? undefined : JSON.stringify(body));
    };
    // A browser's request carries an Origin; the coding tool's never does.
    if (request.headers.origin || request.headers.host !== `127.0.0.1:${this.port}`) return send(403);
    const caller = this.caller(request.headers.authorization ?? "");
    if (caller === null) return send(401);
    if (new URL(request.url ?? "/", "http://127.0.0.1").pathname !== "/mcp") return send(404);
    if (request.method !== "POST") return send(405); // no server-sent stream, no sessions to end
    let raw = "";
    for await (const chunk of request) {
      raw += chunk;
      if (raw.length > MAX_BODY) return send(413);
    }
    let message: Rpc | Rpc[];
    try {
      message = JSON.parse(raw) as Rpc | Rpc[];
    } catch {
      return send(400, { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Not JSON" } });
    }
    const answers = (await Promise.all((Array.isArray(message) ? message : [message]).map((one) => this.answer(one, caller)))).filter(
      (answer) => answer !== null,
    );
    if (!answers.length) return send(202); // only notifications
    send(200, Array.isArray(message) ? answers : answers[0]);
  }

  /** Whose token this is, compared in constant time; null when it's none of them. */
  private caller(header: string): string | null {
    const given = Buffer.from(header);
    let found: string | null = null;
    for (const [token, caller] of this.callers) {
      const expected = Buffer.from(`Bearer ${token}`);
      if (given.length === expected.length && crypto.timingSafeEqual(given, expected)) found = caller;
    }
    return found;
  }

  private async answer(message: Rpc, caller: string): Promise<Record<string, unknown> | null> {
    if (message.id === undefined || message.id === null) return null; // a notification: nothing to say
    const result = (value: unknown) => ({ jsonrpc: "2.0", id: message.id, result: value });
    switch (message.method) {
      case "initialize": {
        const asked = message.params?.protocolVersion;
        return result({
          protocolVersion: typeof asked === "string" && PROTOCOLS.includes(asked) ? asked : PROTOCOLS[0],
          capabilities: { tools: {} },
          serverInfo: { name: this.name, version: this.version },
        });
      }
      case "ping":
        return result({});
      case "tools/list":
        return result({ tools: this.tools.list(caller) });
      case "tools/call": {
        const name = message.params?.name;
        const args = message.params?.arguments;
        try {
          if (typeof name !== "string" || !this.tools.list(caller).some((tool) => tool.name === name)) throw new Error(`No tool named ${String(name)}`);
          return result({ content: await this.tools.call(name, args && typeof args === "object" ? (args as Record<string, unknown>) : {}, caller) });
        } catch (error) {
          return result({ content: [{ type: "text", text: error instanceof Error ? error.message : String(error) }], isError: true });
        }
      }
      default:
        return { jsonrpc: "2.0", id: message.id, error: { code: -32601, message: `Unknown method ${String(message.method)}` } };
    }
  }
}
