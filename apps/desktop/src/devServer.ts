// Kai's app on this computer: on a turn coding here, Kai can start the project's app in its own worktree,
// with the command the person saved for that folder (Settings → Browser), and open it in the Browser pane to
// check its change. Kai can't choose or change the command; the person typed it. It still runs the code Kai
// just wrote, on this computer and without a sandbox, so the person turns it on per folder and the setting says
// so. The command's environment has none of the app's, the runner's or a provider's credentials
// (devServerRules.ts `serverEnv`). One app per folder at a time: it stops when the turn ends, when Kai starts it
// again, when its runner stops, and when the app quits.
import { type ChildProcess, execFile, spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

import { app } from "electron";

import { cleanCommand, type DevCommand, Lines, readCommands, serverEnv, validPort } from "./devServerRules";
import type { Content, Tool } from "./mcp";

const READY_SECONDS = 180; // installing dependencies first can take a while
const STOP_GRACE_MS = 5_000;

interface Running {
  child: ChildProcess;
  worktree: string;
  port: number;
  command: string;
  output: Lines;
  exited: number | null;
}

export class DevServers {
  private saved: Record<string, DevCommand>;
  private readonly running = new Map<string, Running>();

  constructor(private readonly file = path.join(app.getPath("userData"), "dev-servers.json")) {
    let raw: string | null = null;
    try {
      raw = fs.readFileSync(file, "utf8");
    } catch {
      // Nothing saved yet.
    }
    this.saved = readCommands(raw);
  }

  /** The saved commands, by folder. */
  get commands(): Record<string, DevCommand> {
    return { ...this.saved };
  }

  /** Save a folder's command (null forgets it, and stops its app). */
  async save(folder: string, given: { command?: unknown; port?: unknown } | null): Promise<Record<string, DevCommand>> {
    if (given === null) {
      delete this.saved[folder];
      await this.stop(folder);
    } else {
      const command = cleanCommand(given.command);
      if (!command) throw new Error("Enter the command that starts the app, on one line");
      if (given.port !== null && given.port !== undefined && validPort(given.port) === null) throw new Error("The port is a number from 1024 to 65535");
      this.saved[folder] = { command, port: validPort(given.port) };
    }
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, JSON.stringify(this.saved, null, 2));
    return this.commands;
  }

  /** Start a folder's app in a worktree (stopping one already running for it); resolves with its address once it answers. */
  async start(folder: string, worktree: string): Promise<{ url: string; command: string; output: string }> {
    const saved = this.saved[folder];
    if (!saved) throw new Error("No command is saved to start this project's app.");
    await this.stop(folder);
    const port = saved.port ?? (await freePort());
    if (await answers(port))
      throw new Error(
        `Something on this computer already listens on port ${port} (the person's own dev server?), so the app couldn't start there. ` +
          "Go on without the app, and say so: the person can stop it, or clear the port in Settings → Browser so a free one is picked.",
      );
    const output = new Lines();
    const child = spawn(saved.command, {
      cwd: worktree,
      env: serverEnv(process.env, port),
      shell: true,
      windowsHide: true,
      detached: process.platform !== "win32", // a group of its own, so stopping it reaches what it started
      stdio: ["ignore", "pipe", "pipe"],
    });
    const running: Running = { child, worktree, port, command: saved.command, output, exited: null };
    this.running.set(folder, running);
    child.stdout?.on("data", (chunk) => output.push(String(chunk)));
    child.stderr?.on("data", (chunk) => output.push(String(chunk)));
    child.on("error", (error) => output.push(`\n${error.message}\n`));
    child.on("close", (code) => {
      running.exited = code ?? -1;
    });
    const url = `http://localhost:${port}/`;
    for (let waited = 0; waited < READY_SECONDS * 1000; waited += 500) {
      if (running.exited !== null) {
        if (this.running.get(folder) === running) this.running.delete(folder);
        throw new Error(`The app's command ended (${running.exited}) before it answered on port ${port}. Its output:\n${output.tail(60)}`);
      }
      if (await answers(port)) return { url, command: saved.command, output: output.tail(30) };
      await wait(500);
    }
    await this.stop(folder);
    throw new Error(`The app didn't answer on port ${port} within ${READY_SECONDS} seconds, so it was stopped. Its output:\n${output.tail(60)}`);
  }

  /** What a folder's app has printed lately. */
  logs(folder: string): string | null {
    const running = this.running.get(folder);
    if (!running) return null;
    const state = running.exited === null ? `running on port ${running.port}` : `ended (${running.exited})`;
    return `The app (${running.command}) is ${state}.\n\n${running.output.tail() || "No output yet."}`;
  }

  /** Stop a folder's app, and everything it started; resolves once it has ended. */
  async stop(folder: string): Promise<void> {
    const running = this.running.get(folder);
    this.running.delete(folder);
    if (running) await end(running);
  }

  /** Whether any app Kai started is running. */
  get active(): boolean {
    return this.running.size > 0;
  }

  async stopAll(): Promise<void> {
    await Promise.all([...this.running.keys()].map((folder) => this.stop(folder)));
  }
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Whether something on this computer accepts connections on a port (IPv4 or IPv6: dev servers bind either). */
async function answers(port: number): Promise<boolean> {
  const one = (host: string) =>
    new Promise<boolean>((resolve) => {
      const socket = net.connect({ host, port });
      const done = (open: boolean) => {
        socket.destroy();
        resolve(open);
      };
      socket.setTimeout(1000, () => done(false));
      socket.once("connect", () => done(true));
      socket.once("error", () => done(false));
    });
  return (await Promise.all([one("127.0.0.1"), one("::1")])).some(Boolean);
}

/** A port nothing listens on now. */
function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as net.AddressInfo;
      server.close(() => resolve(port));
    });
  });
}

function end(running: Running): Promise<void> {
  const { child } = running;
  if (running.exited !== null || !child.pid) return Promise.resolve();
  const ended = new Promise<void>((resolve) => child.once("close", () => resolve()));
  if (process.platform === "win32") {
    execFile("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true }, () => undefined);
  } else {
    const group = (signal: NodeJS.Signals) => {
      try {
        process.kill(-child.pid!, signal);
      } catch {
        // Already gone.
      }
    };
    group("SIGTERM");
    const kill = setTimeout(() => group("SIGKILL"), STOP_GRACE_MS);
    void ended.then(() => clearTimeout(kill));
  }
  return Promise.race([ended, wait(STOP_GRACE_MS * 2)]);
}

const APP_TOOLS: Tool[] = [
  {
    name: "app_start",
    description:
      "Start the project's app in your worktree, with the command the person saved for it (you can't choose or change it), " +
      "and wait until it answers. Returns its address on this computer, to open with browser_navigate. Starting it again restarts it, " +
      "for example after a change the dev server doesn't reload. It stops when your turn ends.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "app_logs",
    description: "What the app you started has printed lately: build errors, server errors, its address.",
    inputSchema: { type: "object", properties: {} },
  },
];

/** The app tools for a caller (a runner's folder) on its current turn. */
export class KaiApp {
  constructor(
    private readonly servers: DevServers,
    /** The worktree of the turn a runner's folder is coding now, or null. */
    private readonly worktreeOf: (folder: string) => string | null,
    /** Whether Kai may use the browser at all here (Settings → Browser). */
    private readonly allowed: () => boolean,
  ) {}

  list(folder: string): Tool[] {
    return this.allowed() && this.servers.commands[folder] ? APP_TOOLS : [];
  }

  async call(name: string, folder: string): Promise<Content[]> {
    if (name === "app_logs") return [{ type: "text", text: this.servers.logs(folder) ?? "The app isn't running: start it with app_start." }];
    const worktree = this.worktreeOf(folder);
    if (!worktree) throw new Error("No turn is coding in this project on this computer now.");
    const started = await this.servers.start(folder, worktree);
    return [
      {
        type: "text",
        text: `The app is running at ${started.url} (started with: ${started.command}). Open it with browser_navigate.\n\nIts output so far:\n${started.output || "(none)"}`,
      },
    ];
  }
}
