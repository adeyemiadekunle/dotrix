// What a command's recorded output says, read without running anything: a test run's counts and failures
// (pytest, Vitest, Jest, Go, Cargo) and the last stack trace in it (Python, JavaScript). Codes shows them as
// AI Elements' Test Results and Stack Trace (components/AgentTrace.tsx). The text is data from the sandbox,
// so nothing here does more than match lines.

interface TestFailure {
  name: string;
  detail?: string;
}

export interface TestRun {
  passed: number;
  failed: number;
  skipped: number;
  failures: TestFailure[];
}

interface StackFrame {
  text: string;
  file?: string;
  line?: number;
  /** A framework's or library's frame, not the project's own. */
  vendor: boolean;
}

export interface StackTrace {
  error: string;
  frames: StackFrame[];
}

// eslint-disable-next-line no-control-regex
const ANSI = /\u001b\[[0-9;]*[A-Za-z]/g;
const clean = (text: string) => text.replace(ANSI, "").replace(/\r/g, "");

const count = (text: string, word: RegExp) => Number(word.exec(text)?.[1] ?? 0);

function counts(summary: string): Omit<TestRun, "failures"> {
  return {
    passed: count(summary, /(\d+) passed/),
    failed: count(summary, /(\d+) failed/) + count(summary, /(\d+) errors?\b/),
    skipped: count(summary, /(\d+) (?:skipped|ignored|todo)/),
  };
}

const unique = (failures: TestFailure[]) => failures.filter((f, i) => failures.findIndex((o) => o.name === f.name) === i).slice(0, 50);

/** A test run's counts and failures, or null when the output isn't one. */
export function parseTests(output: string): TestRun | null {
  const text = clean(output);
  // pytest: "==== 1 failed, 23 passed, 2 skipped in 1.20s ====" and "FAILED tests/x.py::test_y - AssertionError"
  const pytest = /^=+ ([^=\n]*\b(?:passed|failed|error|errors|skipped)\b[^=\n]*?) in [\d.]+s[^=\n]*=+\s*$/m.exec(text);
  if (pytest) {
    const failures = [...text.matchAll(/^(?:FAILED|ERROR) (\S+)(?: - (.*))?$/gm)].map((m) => ({ name: m[1]!, detail: m[2]?.trim() || undefined }));
    return { ...counts(pytest[1]!), failures: unique(failures) };
  }
  // Jest: "Tests:       1 failed, 23 passed, 24 total" and "  ● Suite › name"
  const jest = /^Tests:\s+(.+)$/m.exec(text);
  if (jest) {
    const failures = [...text.matchAll(/^\s*● (.+)$/gm)].map((m) => m[1]!.trim()).filter((n) => !/^Test suite failed to run/.test(n));
    return { ...counts(jest[1]!), failures: unique(failures.map((name) => ({ name }))) };
  }
  // Vitest: "      Tests  1 failed | 23 passed (24)" and " FAIL  src/a.test.ts > suite > name"
  const vitest = /^\s*Tests\s+(\d+ (?:passed|failed|skipped|todo)[^\n]*?)\s*\(\d+\)\s*$/m.exec(text);
  if (vitest) {
    const failures = [...text.matchAll(/^\s*FAIL\s+(.+?)\s*$/gm)].map((m) => ({ name: m[1]!.replace(/\s+\[[^\]]*\]$/, "") }));
    return { ...counts(vitest[1]!), failures: unique(failures) };
  }
  // Cargo: "test result: FAILED. 3 passed; 1 failed; 0 ignored" and "test path::name ... FAILED"
  const cargo = [...text.matchAll(/^test result: \w+\. (.+)$/gm)];
  if (cargo.length) {
    const total = cargo
      .map((m) => counts(m[1]!))
      .reduce((a, b) => ({ passed: a.passed + b.passed, failed: a.failed + b.failed, skipped: a.skipped + b.skipped }));
    const failures = [...text.matchAll(/^test (\S+) \.\.\. FAILED$/gm)].map((m) => ({ name: m[1]! }));
    return { ...total, failures: unique(failures) };
  }
  // Go: "--- PASS: TestX (0.00s)" / "--- FAIL: TestY (0.01s)" / "--- SKIP: TestZ"
  const go = [...text.matchAll(/^\s*--- (PASS|FAIL|SKIP): (\S+)/gm)];
  if (go.length) {
    const of = (kind: string) => go.filter((m) => m[1] === kind);
    return { passed: of("PASS").length, failed: of("FAIL").length, skipped: of("SKIP").length, failures: unique(of("FAIL").map((m) => ({ name: m[2]! }))) };
  }
  return null;
}

const VENDOR = /node_modules|site-packages|dist-packages|node:internal|<frozen |\/usr\/lib\/|internal\/(?:modules|process)/;

/** The last stack trace in some text, or null when there isn't one. */
export function parseStack(output: string): StackTrace | null {
  const lines = clean(output).split("\n");
  // Python: "Traceback (most recent call last):", then '  File "x.py", line 3, in f' and its code, then the error.
  const start = lines.findLastIndex((l) => /^Traceback \(most recent call last\):/.test(l.trim()));
  if (start >= 0) {
    const frames: StackFrame[] = [];
    let i = start + 1;
    for (; i < lines.length; i++) {
      const m = /^\s*File "([^"]+)", line (\d+)(?:, in (.+))?/.exec(lines[i]!);
      if (m) {
        const code = lines[i + 1] && !/^\s*File "/.test(lines[i + 1]!) && /^\s{4,}/.test(lines[i + 1]!) ? lines[++i]!.trim() : "";
        frames.push({ text: `${m[3] ?? "<module>"} (${m[1]}:${m[2]})${code ? ` · ${code}` : ""}`, file: m[1], line: Number(m[2]), vendor: VENDOR.test(m[1]!) });
      } else if (/^\s+\^+\s*$/.test(lines[i]!) || /^\s{4,}/.test(lines[i]!)) continue;
      else break;
    }
    const error = lines
      .slice(i)
      .find((l) => l.trim())
      ?.trim();
    return error ? { error, frames } : null;
  }
  // JavaScript: "TypeError: message", then "    at fn (file:line:col)" or "    at file:line:col".
  const at = lines.findIndex((l) => /^\s+at .+/.test(l));
  if (at > 0) {
    const head = lines.slice(0, at).findLastIndex((l) => /^\s*(?:Uncaught )?\w*(?:Error|Exception)\b/.test(l));
    if (head < 0) return null;
    const frames: StackFrame[] = [];
    for (let i = at; i < lines.length && /^\s+at /.test(lines[i]!); i++) {
      const text = lines[i]!.trim().replace(/^at /, "");
      const m = /\(?((?:[A-Za-z]:)?[^\s()]+?):(\d+)(?::\d+)?\)?$/.exec(text);
      frames.push({ text, file: m?.[1], line: m ? Number(m[2]) : undefined, vendor: VENDOR.test(text) });
    }
    return { error: lines[head]!.trim(), frames };
  }
  return null;
}

/** A frame's file as a path in the repository, when it is one: relative, or under a checkout's root. */
export function repoPath(file: string | undefined, known: string[] = []): string | undefined {
  if (!file || VENDOR.test(file)) return undefined;
  const path = file.replace(/^file:\/\//, "");
  const hit = known.find((k) => path === k || path.endsWith(`/${k}`));
  if (hit) return hit;
  if (!path.startsWith("/") && !/^[A-Za-z]:/.test(path) && !path.startsWith("<")) return path.replace(/^\.\//, "");
  return undefined;
}
