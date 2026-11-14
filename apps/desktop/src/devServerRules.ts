// The rules for starting a project's app for Kai (devServer.ts). Pure, so node --test checks them.

/** What a person saved for one folder: the command that starts its app, and the port it listens on (null: the app picks one and passes it as PORT). */
export interface DevCommand {
  command: string;
  port: number | null;
}

const MAX_COMMAND = 500;

/** A port a dev server may listen on: not a privileged one. */
export function validPort(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 1024 && value <= 65535 ? value : null;
}

/** A command as a person saved it: one line, not empty, not too long. Null when it isn't one. */
export function cleanCommand(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const command = value.trim();
  return command && command.length <= MAX_COMMAND && !/[\r\n\0]/.test(command) ? command : null;
}

/** The saved commands, by folder, from whatever their file holds (anything malformed is left out). */
export function readCommands(raw: string | null): Record<string, DevCommand> {
  let saved: unknown;
  try {
    saved = JSON.parse(raw ?? "");
  } catch {
    return {};
  }
  const found: Record<string, DevCommand> = {};
  if (!saved || typeof saved !== "object" || Array.isArray(saved)) return found;
  for (const [folder, entry] of Object.entries(saved as Record<string, unknown>)) {
    const command = cleanCommand((entry as { command?: unknown } | null)?.command);
    if (!command) continue;
    found[folder] = { command, port: validPort((entry as { port?: unknown }).port) };
  }
  return found;
}

// What the app's command gets in its environment: what it needs to run, and nothing of the app's, the runner's or
// a provider's credentials (dotrix_cli/toolenv.py keeps the coding tool's the same way).
const EXECUTION_ENV = new Set([
  "PATH",
  "PATHEXT",
  "SYSTEMROOT",
  "WINDIR",
  "COMSPEC",
  "PROGRAMDATA",
  "APPDATA",
  "LOCALAPPDATA",
  "HOME",
  "USERPROFILE",
  "HOMEDRIVE",
  "HOMEPATH",
  "USER",
  "LOGNAME",
  "SHELL",
  "TMP",
  "TEMP",
  "TMPDIR",
  "LANG",
  "LANGUAGE",
  "LC_ALL",
  "LC_CTYPE",
  "TERM",
  "TZ",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "XDG_CACHE_HOME",
  "SSL_CERT_FILE",
  "SSL_CERT_DIR",
  "NODE_EXTRA_CA_CERTS",
  "NVM_DIR",
  "PNPM_HOME",
  "VOLTA_HOME",
  "COREPACK_HOME",
]);

/** The command's environment: the execution settings from `environ`, its port, and no browser of its own. */
export function serverEnv(environ: Record<string, string | undefined>, port: number): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(environ)) if (value !== undefined && EXECUTION_ENV.has(key.toUpperCase())) env[key] = value;
  env.PORT = String(port);
  env.BROWSER = "none"; // a dev server that opens a browser would open the person's, not the pane
  return env;
}

/** Output kept as lines, the last `limit` of them. */
export class Lines {
  private readonly kept: string[] = [];
  private partial = "";

  constructor(private readonly limit = 300) {}

  push(chunk: string): void {
    const parts = (this.partial + chunk).split(/\r?\n/);
    this.partial = parts.pop() ?? "";
    for (const line of parts) this.add(line);
    if (this.partial.length > 4000) {
      this.add(this.partial);
      this.partial = "";
    }
  }

  private add(line: string): void {
    // Colour codes and the like mean nothing to Kai.
    // eslint-disable-next-line no-control-regex
    this.kept.push(line.replace(/\u001b\[[0-9;?]*[A-Za-z]/g, "").slice(0, 2000));
    if (this.kept.length > this.limit) this.kept.shift();
  }

  /** The last `count` lines (all of them by default), the line still being written included. */
  tail(count = this.limit): string {
    const all = this.partial ? [...this.kept, this.partial] : this.kept;
    return all.slice(-count).join("\n");
  }
}
