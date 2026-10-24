// The desktop app codes local turns itself: it runs `dotrix runner` in the background for each folder
// a person picks (a checkout of a project's repo), with the dotrix CLI bundled in the app
// (resources/dotrix, built by apps/cli/scripts/standalone.py) and the sandbox runtime bundled too
// (sandbox.ts). Like the CLI's runner, the coding tool is the one signed in on this computer; the
// platform never sends a provider key or GitHub token here. The CLI signs in with a device code the
// person approves in the app's own window (where they're already signed in), and keeps its token in
// the OS keychain: the app never sees it.
import { type ChildProcess, execFile, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

import { app, BrowserWindow, dialog, shell } from "electron";

import { sandboxEnv } from "./sandbox";

type RunnerState = "starting" | "waiting" | "coding" | "stopped" | "failed";

export interface RunnerStatus {
  folder: string;
  workspace: string;
  projectKey: string;
  state: RunnerState;
  runnerId?: string;
  name?: string;
  isolation?: string;
  tools?: string[];
  turn?: { runId: string; issueKey: string; turn: number; worktree: string };
  message?: string; // why it stopped or failed, or the last thing it said
}

interface Saved {
  folder: string;
  workspace: string;
  projectKey: string;
}

const RESTART_MS = [5_000, 15_000, 60_000];

/** Where the bundled CLI is: in the packaged app's resources, else (developing) DOTRIX_CLI, the
 *  folder standalone.py builds into, or a `dotrix` on PATH. */
function cliCommand(): string {
  const exe = process.platform === "win32" ? "dotrix.exe" : "dotrix";
  const candidates = [process.env.DOTRIX_CLI, path.join(process.resourcesPath ?? "", "dotrix", exe), path.join(__dirname, "..", "resources", "dotrix", exe)];
  return candidates.find((c): c is string => Boolean(c) && fs.existsSync(c as string)) ?? "dotrix";
}

export class Runners {
  private statuses = new Map<string, RunnerStatus>();
  private processes = new Map<string, ChildProcess>();
  private failures = new Map<string, number>();
  private quitting = false;

  constructor(
    private apiUrl: string,
    private webUrl: string,
  ) {}

  private get savedFile(): string {
    return path.join(app.getPath("userData"), "runners.json");
  }

  private saved(): Saved[] {
    try {
      const rows = JSON.parse(fs.readFileSync(this.savedFile, "utf8"));
      return Array.isArray(rows) ? rows.filter((r) => typeof r?.folder === "string") : [];
    } catch {
      return [];
    }
  }

  private save(): void {
    const rows: Saved[] = [...this.statuses.values()].map(({ folder, workspace, projectKey }) => ({ folder, workspace, projectKey }));
    fs.mkdirSync(path.dirname(this.savedFile), { recursive: true });
    fs.writeFileSync(this.savedFile, JSON.stringify(rows, null, 2));
  }

  list(): RunnerStatus[] {
    return [...this.statuses.values()];
  }

  /** Start the runners saved on this computer (on launch). */
  resume(): void {
    for (const row of this.saved()) {
      this.statuses.set(row.folder, { ...row, state: "starting" });
      this.start(row.folder);
    }
    this.changed();
  }

  /** Stop every runner (quitting): resolves once they, and the tools they started, have ended. */
  async stopAll(): Promise<void> {
    this.quitting = true;
    await Promise.all([...this.processes.values()].map(terminate));
  }

  get running(): boolean {
    return this.processes.size > 0;
  }

  private env(): NodeJS.ProcessEnv {
    // The CLI's own runtime picks the API from here; srt from the app's bundle.
    return { ...process.env, ...sandboxEnv(), DOTRIX_API_URL: this.apiUrl, PYTHONUNBUFFERED: "1" };
  }

  private cli(args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
    return new Promise((resolve) => {
      execFile(cliCommand(), args, { env: this.env(), windowsHide: true, timeout: 5 * 60_000 }, (error, stdout, stderr) => {
        const code = error ? (typeof error.code === "number" ? error.code : 1) : 0;
        resolve({ code, stdout: String(stdout), stderr: String(stderr) });
      });
    });
  }

  /** Whether the bundled CLI is signed in to this app's platform. */
  async signedIn(): Promise<boolean> {
    const { stdout } = await this.cli(["whoami", "--json", "--api-url", this.apiUrl]);
    try {
      return Boolean(JSON.parse(stdout.trim().split("\n").pop() ?? "{}").signed_in);
    } catch {
      return false;
    }
  }

  /** Sign the CLI in: a device code, approved in a window of this app (already signed in there). */
  signIn(parent: BrowserWindow | null): Promise<void> {
    return new Promise((resolve, reject) => {
      const child = spawn(cliCommand(), ["login", "--json", "--client-name", `dotrix desktop (${os.hostname()})`, "--api-url", this.apiUrl], {
        env: this.env(),
        windowsHide: true,
      });
      let approval: BrowserWindow | null = null;
      let errors = "";
      let settled = false;
      const settle = (error?: Error) => {
        if (settled) return;
        settled = true;
        if (approval && !approval.isDestroyed()) approval.close();
        if (error) reject(error);
        else resolve();
      };
      // The CLI can't start (missing from the bundle, not executable): say so, rather than throw in here.
      child.on("error", (error) => settle(new Error(`The dotrix CLI couldn't start: ${error.message}`)));
      child.stderr?.on("data", (chunk) => (errors += String(chunk)));
      readline.createInterface({ input: child.stdout! }).on("line", (line) => {
        const event = parse(line);
        if (event?.event !== "code" || typeof event.verification_uri_complete !== "string") return;
        const url = event.verification_uri_complete;
        if (sameOrigin(url, this.webUrl)) {
          approval = new BrowserWindow({
            parent: parent ?? undefined,
            modal: Boolean(parent),
            width: 520,
            height: 640,
            title: "Sign in this computer's runner",
            webPreferences: { contextIsolation: true, sandbox: true },
          });
          void approval.loadURL(url);
        } else {
          void shell.openExternal(url);
        }
      });
      child.on("close", (code) => settle(code === 0 ? undefined : new Error(lastLine(errors) ?? "Signing in didn't finish")));
    });
  }

  /** Pick a folder for a project, link it, and start its runner. */
  async add(parent: BrowserWindow | null, workspace: string, projectKey: string): Promise<RunnerStatus | null> {
    const picked = await (parent
      ? dialog.showOpenDialog(parent, {
          title: `Choose your checkout of ${projectKey}'s repository`,
          properties: ["openDirectory"],
        })
      : dialog.showOpenDialog({ title: `Choose your checkout of ${projectKey}'s repository`, properties: ["openDirectory"] }));
    const folder = picked.canceled ? undefined : picked.filePaths[0];
    if (!folder) return null;
    if (!fs.existsSync(path.join(folder, ".git"))) throw new Error("That folder isn't a git checkout: choose the repository's folder");
    if (!(await this.signedIn())) await this.signIn(parent);
    const linked = await this.cli(["link", folder, "--workspace", workspace, "--project", projectKey, "--api-url", this.apiUrl]);
    if (linked.code !== 0) throw new Error(lastLine(linked.stderr) ?? `Couldn't link ${folder} to ${projectKey}`);
    await this.remove(folder); // a runner already there for it ends first, or the new one couldn't start
    const status: RunnerStatus = { folder, workspace, projectKey, state: "starting" };
    this.statuses.set(folder, status);
    this.save();
    this.start(folder);
    this.changed();
    return status;
  }

  /** Stop a folder's runner and forget the folder; resolves once its process has ended. */
  async remove(folder: string): Promise<void> {
    const child = this.processes.get(folder);
    this.statuses.delete(folder);
    this.failures.delete(folder);
    this.save();
    this.changed();
    if (child) await terminate(child);
  }

  async restart(folder: string): Promise<void> {
    const child = this.processes.get(folder);
    if (child) await terminate(child);
    this.failures.delete(folder);
    this.start(folder);
  }

  private start(folder: string): void {
    const status = this.statuses.get(folder);
    if (!status || this.processes.has(folder)) return;
    Object.assign(status, { state: "starting", message: undefined, turn: undefined });
    const child = spawn(cliCommand(), ["runner", "--json", "--project", folder], { cwd: folder, env: this.env(), windowsHide: true });
    this.processes.set(folder, child);
    let errors = "";
    child.stderr?.on("data", (chunk) => (errors = (errors + String(chunk)).slice(-4000)));
    readline.createInterface({ input: child.stdout! }).on("line", (line) => {
      const event = parse(line);
      if (!event) return;
      if (event.event === "registered") {
        Object.assign(status, {
          state: "waiting",
          runnerId: event.runner_id,
          name: event.name,
          isolation: event.isolation,
          tools: event.tools,
        });
        this.failures.delete(folder);
      } else if (event.event === "turn") {
        status.state = "coding";
        status.turn = { runId: String(event.run_id), issueKey: String(event.issue_key), turn: Number(event.turn), worktree: String(event.worktree) };
      } else if (event.event === "done") {
        status.state = "waiting";
        status.turn = undefined;
      } else if (event.event === "log" && typeof event.text === "string") {
        status.message = event.text.trim();
      }
      this.changed();
    });
    child.on("error", (error) => {
      errors += String(error.message);
    });
    child.on("close", (code) => {
      this.processes.delete(folder);
      if (this.quitting || this.statuses.get(folder) !== status) return;
      status.state = code === 0 ? "stopped" : "failed";
      status.turn = undefined;
      status.message = lastLine(errors) ?? (code === 0 ? "Stopped" : `The runner exited (${code})`);
      this.changed();
      // Back by itself (the platform or the network may return); after a few tries it waits for Restart.
      const tries = (this.failures.get(folder) ?? 0) + 1;
      this.failures.set(folder, tries);
      if (tries <= RESTART_MS.length) setTimeout(() => this.statuses.get(folder) === status && this.start(folder), RESTART_MS[tries - 1]);
    });
  }

  private changed(): void {
    const list = this.list();
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.isDestroyed() && sameOrigin(win.webContents.getURL(), this.webUrl)) win.webContents.send("dotrix:runners", list);
    }
  }
}

// -- helpers -----------------------------------------------------------------------------------

// What the CLI prints with --json (dotrix_cli: cli.py `_json_line`, runner.py `notify`).
interface CliEvent {
  event?: string;
  text?: string;
  runner_id?: string;
  name?: string;
  isolation?: string;
  tools?: string[];
  run_id?: string;
  issue_key?: string;
  turn?: number;
  worktree?: string;
  verification_uri_complete?: string;
}

function parse(line: string): CliEvent | null {
  try {
    const value = JSON.parse(line);
    return value && typeof value === "object" ? value : null;
  } catch {
    return null; // anything else the CLI prints
  }
}

function lastLine(text: string): string | undefined {
  return (
    text
      .trim()
      .split(/\r?\n/)
      .filter((l) => l.trim())
      .pop()
      ?.trim() || undefined
  );
}

export function sameOrigin(url: string, other: string): boolean {
  try {
    return new URL(url).origin === new URL(other).origin;
  } catch {
    return false;
  }
}

/** Stop a runner, and with it the coding tool it started; resolves once the runner has ended. On
 *  Windows the whole tree goes at once. Elsewhere SIGINT lets the CLI stop the tool's own process group
 *  first (dotrix_cli: runner.py), and SIGKILL follows only if it hasn't ended in 10 s. */
function terminate(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null || !child.pid) return Promise.resolve();
  const ended = new Promise<void>((resolve) => child.once("close", () => resolve()));
  if (process.platform === "win32") {
    execFile("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true }, () => undefined);
  } else {
    child.kill("SIGINT");
    const kill = setTimeout(() => child.exitCode === null && child.kill("SIGKILL"), 10_000);
    void ended.then(() => clearTimeout(kill));
  }
  return ended;
}
