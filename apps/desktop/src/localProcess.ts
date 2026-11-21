import { type ChildProcess, execFile } from "node:child_process";

const STOP_GRACE_MS = 5_000;

export function stopLocalProcess(child: ChildProcess, ended: Promise<void>): Promise<void> {
  if (!child.pid) return ended;
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
  return Promise.race([
    ended,
    new Promise<void>((resolve) => {
      const timeout = setTimeout(resolve, STOP_GRACE_MS * 2);
      void ended.then(() => clearTimeout(timeout));
    }),
  ]);
}
