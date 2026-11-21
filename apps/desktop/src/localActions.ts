import { type ChildProcess, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { cleanCommand, Lines, serverEnv } from "./devServerRules";
import { stopLocalProcess } from "./localProcess";
import { reserveLocalAction } from "./worktree";

export interface LocalProfile {
  setup: string;
  tests: string;
}

export function localProfile(value: unknown): LocalProfile {
  if (!value || typeof value !== "object") throw new Error("Enter a local profile");
  const { setup, tests } = value as Partial<LocalProfile>;
  const command = (text: unknown) => {
    if (typeof text === "string" && !text.trim()) return "";
    const cleaned = cleanCommand(text);
    if (!cleaned) throw new Error("Commands must fit on one line and be at most 500 characters");
    return cleaned;
  };
  return { setup: command(setup), tests: command(tests) };
}

export class LocalActions {
  private readonly profiles = new Map<string, LocalProfile>();
  private readonly running = new Map<ChildProcess, () => Promise<boolean>>();

  constructor(private readonly file: string) {
    try {
      const entries: unknown = JSON.parse(fs.readFileSync(file, "utf8"));
      if (!entries || typeof entries !== "object") return;
      for (const [folder, value] of Object.entries(entries)) {
        try {
          this.profiles.set(folder, localProfile(value));
        } catch {
          // A malformed profile never provides commands.
        }
      }
    } catch {
      // No readable saved profiles.
    }
  }

  profile(folder: string): LocalProfile {
    return this.profiles.get(folder) ?? { setup: "", tests: "" };
  }

  save(folder: string, profile: LocalProfile): LocalProfile {
    const next = new Map(this.profiles).set(folder, profile);
    const temporary = `${this.file}.tmp`;
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(temporary, JSON.stringify(Object.fromEntries(next), null, 2), { mode: 0o600 });
    fs.renameSync(temporary, this.file);
    this.profiles.set(folder, profile);
    return profile;
  }

  async run(folder: string, tree: string, action: keyof LocalProfile) {
    const command = this.profile(folder)[action];
    if (!command) throw new Error("Save a command for this action first");
    const release = await reserveLocalAction(folder, tree);
    const output = new Lines();
    let child;
    try {
      child = spawn(command, {
        cwd: tree,
        env: serverEnv(process.env),
        shell: true,
        windowsHide: true,
        detached: process.platform !== "win32",
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      release();
      throw error;
    }
    child.stdout.on("data", (chunk) => output.push(String(chunk)));
    child.stderr.on("data", (chunk) => output.push(String(chunk)));
    child.on("error", (error) => output.push(`\n${error.message}\n`));
    const result = new Promise<number | null>((resolve) => child.once("close", resolve));
    const ended = result.then(() => undefined);
    let stopped!: (exitCode: null) => void;
    const interrupted = new Promise<null>((resolve) => {
      stopped = resolve;
    });
    let stopping: Promise<boolean> | undefined;
    const stop = () =>
      (stopping ??= stopLocalProcess(child, ended).then((confirmed) => {
        stopped(null);
        return confirmed;
      }));
    this.running.set(child, stop);
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      void stop();
    }, 5 * 60_000);
    let confirmed = false;
    try {
      const exitCode = await Promise.race([result, interrupted]);
      clearTimeout(timeout);
      confirmed = await (stopping ?? (process.platform === "win32" ? true : stop()));
      if (!confirmed) throw new Error("Could not confirm that the local command stopped. The worktree remains reserved.");
      return { exitCode: timedOut ? null : exitCode, output: output.tail(), timedOut };
    } finally {
      clearTimeout(timeout);
      this.running.delete(child);
      release(!confirmed);
    }
  }

  get active(): boolean {
    return this.running.size > 0;
  }

  async stopAll(): Promise<void> {
    await Promise.all([...this.running.values()].map((stop) => stop()));
  }
}
