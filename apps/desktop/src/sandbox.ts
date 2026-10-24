// The sandbox runtime (srt, @anthropic-ai/sandbox-runtime) ships inside the desktop app, pinned to
// the version the CLI installs (apps/cli: dotrix_cli/sandbox.py). The runner the app starts finds it
// through DOTRIX_SRT and runs it with the app's own Node (DOTRIX_SRT_NODE: this executable, run as
// Node), so a person installs nothing to have their local coding turns isolated.
// Packaging note: srt's vendor/ binaries (seccomp helpers, srt-win.exe) must stay real files, so
// whichever packager builds the app has to unpack @anthropic-ai/sandbox-runtime from the asar.
import path from "node:path";

/** srt's CLI entry inside this app, or null if the package is missing. */
function bundledSrt(): string | null {
  try {
    const pkg = require.resolve("@anthropic-ai/sandbox-runtime/package.json");
    return path.join(path.dirname(pkg), "dist", "cli.js").replace(`app.asar${path.sep}`, `app.asar.unpacked${path.sep}`);
  } catch {
    return null;
  }
}

/** What a runner started by the app needs in its environment to use the bundled srt. */
export function sandboxEnv(): Record<string, string> {
  const cli = bundledSrt();
  return cli ? { DOTRIX_SRT: cli, DOTRIX_SRT_NODE: process.execPath } : {};
}
