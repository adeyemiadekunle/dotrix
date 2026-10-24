// The sandbox runtime (srt, @anthropic-ai/sandbox-runtime) ships inside the desktop app, pinned to
// the version the CLI installs (apps/cli: dotrix_cli/sandbox.py). The runner the app starts finds it
// through DOTRIX_SRT and runs it with the app's own Node (DOTRIX_SRT_NODE: this executable, run as
// Node), so a person installs nothing to have their local coding turns isolated. On Windows srt also
// needs a one-time setup per machine (an administrator, once): the app offers it on first launch.
// Packaging note: srt's vendor/ binaries (seccomp helpers, srt-win.exe) must stay real files, so
// whichever packager builds the app has to unpack @anthropic-ai/sandbox-runtime from the asar.
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { app, dialog } from "electron";

/** srt's package folder inside this app, or null if it's missing. */
function bundledPackage(): string | null {
  try {
    const pkg = path.dirname(require.resolve("@anthropic-ai/sandbox-runtime/package.json"));
    return pkg.replace(`app.asar${path.sep}`, `app.asar.unpacked${path.sep}`);
  } catch {
    return null;
  }
}

/** What a runner started by the app needs in its environment to use the bundled srt. */
export function sandboxEnv(): Record<string, string> {
  const pkg = bundledPackage();
  return pkg ? { DOTRIX_SRT: path.join(pkg, "dist", "cli.js"), DOTRIX_SRT_NODE: process.execPath } : {};
}

function run(file: string, args: string[], env?: NodeJS.ProcessEnv): Promise<{ code: number; stdout: string }> {
  return new Promise((resolve) => {
    execFile(file, args, { env, windowsHide: true, timeout: 10 * 60_000 }, (error, stdout) => {
      const code = error ? (typeof error.code === "number" ? error.code : 1) : 0;
      resolve({ code, stdout: String(stdout) });
    });
  });
}

/** Whether srt's one-time Windows setup is done here (read with srt-win.exe, no administrator needed). */
async function windowsReady(pkg: string): Promise<boolean> {
  const arch = process.arch === "arm64" ? "arm64" : "x64";
  const { stdout } = await run(path.join(pkg, "vendor", "srt-win", arch, "srt-win.exe"), ["status"]);
  try {
    const status = JSON.parse(stdout);
    return Boolean(status.user?.user?.exists && status.user?.cred_present) && ["installed", "cannot-read"].includes(status.wfp?.state);
  } catch {
    return false;
  }
}

/** On Windows, offer srt's one-time setup (once: a "Not now" is remembered until the next version). */
export async function offerWindowsSandbox(): Promise<void> {
  const pkg = bundledPackage();
  if (process.platform !== "win32" || !pkg || (await windowsReady(pkg))) return;
  const asked = path.join(app.getPath("userData"), "sandbox-setup-asked");
  if (fs.existsSync(asked) && fs.readFileSync(asked, "utf8") === app.getVersion()) return;
  const { response } = await dialog.showMessageBox({
    type: "question",
    buttons: ["Set up", "Not now"],
    defaultId: 0,
    message: "Set up the sandbox for coding on this computer?",
    detail:
      "Kai's local turns run inside a sandbox that keeps them to their worktree and the model's API. " +
      "Windows asks for an administrator once to create it. Without it, local turns run unisolated.",
  });
  fs.mkdirSync(path.dirname(asked), { recursive: true });
  fs.writeFileSync(asked, app.getVersion());
  if (response !== 0) return;
  const { code } = await run(process.execPath, [path.join(pkg, "dist", "cli.js"), "windows-install"], {
    ...process.env,
    ELECTRON_RUN_AS_NODE: "1",
  });
  if (code !== 0 && code !== 2) dialog.showErrorBox("Sandbox setup failed", "Run `dotrix sandbox install` in a terminal to see why.");
}
