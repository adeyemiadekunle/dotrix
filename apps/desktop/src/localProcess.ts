import { type ChildProcess, execFile } from "node:child_process";
import { setTimeout as wait } from "node:timers/promises";

const STOP_GRACE_MS = 5_000;

async function stopProcessGroup(pid: number): Promise<boolean> {
  const goneAfter = (signal: NodeJS.Signals | 0) => {
    try {
      process.kill(-pid, signal);
      return false;
    } catch (error) {
      return (error as NodeJS.ErrnoException).code === "ESRCH";
    }
  };
  for (const signal of ["SIGTERM", "SIGKILL"] as const) {
    if (goneAfter(signal)) return true;
    const until = performance.now() + STOP_GRACE_MS;
    while (performance.now() < until) {
      await wait(100);
      if (goneAfter(0)) return true;
    }
  }
  return false;
}

export async function stopLocalProcess(child: ChildProcess, ended: Promise<void>): Promise<boolean> {
  if (!child.pid) {
    await ended;
    return true;
  }
  if (process.platform !== "win32") return stopProcessGroup(child.pid);

  execFile("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true }, () => undefined);
  return Promise.race([
    ended.then(() => true),
    new Promise<false>((resolve) => {
      const timeout = setTimeout(() => resolve(false), STOP_GRACE_MS * 2);
      void ended.then(() => clearTimeout(timeout));
    }),
  ]);
}
