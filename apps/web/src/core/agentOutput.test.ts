import { describe, expect, it } from "vitest";

import { parseStack, parseTests, repoPath } from "./agentOutput";

describe("parseTests", () => {
  it("reads pytest's summary and failures", () => {
    const out = [
      "tests/test_a.py ..F.",
      "FAILED tests/test_a.py::test_refund - AssertionError: 1 != 2",
      "================ 1 failed, 3 passed, 2 skipped in 0.42s ================",
    ].join("\n");
    expect(parseTests(out)).toEqual({
      passed: 3,
      failed: 1,
      skipped: 2,
      failures: [{ name: "tests/test_a.py::test_refund", detail: "AssertionError: 1 != 2" }],
    });
  });

  it("reads Vitest's summary, with colours", () => {
    const out = "\u001b[31m FAIL \u001b[39m src/nav.test.ts > nav > keeps focus\n\n Test Files  1 failed (1)\n      Tests  1 failed | 23 passed (24)";
    expect(parseTests(out)).toEqual({ passed: 23, failed: 1, skipped: 0, failures: [{ name: "src/nav.test.ts > nav > keeps focus" }] });
  });

  it("reads Jest's summary", () => {
    const out = "  ● Billing › formats an invoice\n\nTests:       1 failed, 9 passed, 10 total";
    expect(parseTests(out)).toEqual({ passed: 9, failed: 1, skipped: 0, failures: [{ name: "Billing › formats an invoice" }] });
  });

  it("reads Go and Cargo", () => {
    expect(parseTests("--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.01s)\nFAIL")).toEqual({ passed: 1, failed: 1, skipped: 0, failures: [{ name: "TestB" }] });
    expect(parseTests("test a::b ... FAILED\ntest result: FAILED. 3 passed; 1 failed; 0 ignored")).toEqual({
      passed: 3,
      failed: 1,
      skipped: 0,
      failures: [{ name: "a::b" }],
    });
  });

  it("says nothing of output that isn't a test run", () => {
    expect(parseTests("24 tests passed")).toBeNull();
    expect(parseTests("Compiled successfully")).toBeNull();
  });
});

describe("parseStack", () => {
  it("reads the last Python traceback", () => {
    const out = [
      "Traceback (most recent call last):",
      '  File "/usr/lib/python3.13/runpy.py", line 9, in run',
      "    exec(code)",
      '  File "app/billing.py", line 42, in total',
      "    return sum(x.amount for x in items)",
      "AttributeError: 'NoneType' object has no attribute 'amount'",
    ].join("\n");
    const stack = parseStack(out)!;
    expect(stack.error).toBe("AttributeError: 'NoneType' object has no attribute 'amount'");
    expect(stack.frames.map((f) => [f.file, f.line, f.vendor])).toEqual([
      ["/usr/lib/python3.13/runpy.py", 9, true],
      ["app/billing.py", 42, false],
    ]);
  });

  it("reads a JavaScript stack", () => {
    const out =
      "TypeError: Cannot read properties of undefined (reading 'total')\n    at formatInvoice (app/lib/billing.ts:42:31)\n    at node_modules/react-dom/cjs/x.js:1:2";
    const stack = parseStack(out)!;
    expect(stack.error).toBe("TypeError: Cannot read properties of undefined (reading 'total')");
    expect(stack.frames).toEqual([
      { text: "formatInvoice (app/lib/billing.ts:42:31)", file: "app/lib/billing.ts", line: 42, vendor: false },
      { text: "node_modules/react-dom/cjs/x.js:1:2", file: "node_modules/react-dom/cjs/x.js", line: 1, vendor: true },
    ]);
  });

  it("says nothing without a trace", () => {
    expect(parseStack("error: 'x' is unused")).toBeNull();
  });
});

describe("repoPath", () => {
  it("keeps the repository's own files only", () => {
    expect(repoPath("./src/a.ts")).toBe("src/a.ts");
    expect(repoPath("/work/repo/src/a.ts", ["src/a.ts"])).toBe("src/a.ts");
    expect(repoPath("/usr/lib/python3/x.py")).toBeUndefined();
    expect(repoPath("/tmp/elsewhere.ts")).toBeUndefined();
  });
});
