import { describe, expect, it } from "vitest";

const at = "2026-10-24T12:00:00Z";

describe("the panel's helpers", () => {
  it("reads a turn's diff as files, hunks, and line numbers", async () => {
    const { parseDiff } = await import("./kaiWork");
    const files = parseDiff(
      [
        "diff --git a/src/pay.py b/src/pay.py",
        "index 1..2 100644",
        "--- a/src/pay.py",
        "+++ b/src/pay.py",
        "@@ -1,2 +1,3 @@",
        " class Pay:",
        "-    pass",
        "+    def refund(self, a):",
        "+        return a",
        "diff --git a/new.txt b/new.txt",
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/new.txt",
        "@@ -0,0 +1 @@",
        "+hello",
        "diff --git a/logo.png b/logo.png",
        "GIT binary patch",
        "literal 10",
      ].join("\n"),
    );
    expect(files.map((f) => [f.path, f.status, f.added, f.removed, f.binary])).toEqual([
      ["src/pay.py", "modified", 2, 1, false],
      ["new.txt", "added", 1, 0, false],
      ["logo.png", "modified", 0, 0, true],
    ]);
    expect(files[0]!.hunks[0]!.lines.map((l) => [l.kind, l.old, l.new])).toEqual([
      ["ctx", 1, 1],
      ["del", 2, null],
      ["add", null, 2],
      ["add", null, 3],
    ]);
  });

  it("keeps a hunk's lines that start like a file's header", async () => {
    const { parseDiff } = await import("./kaiWork");
    const [f] = parseDiff(
      [
        "diff --git a/a.c b/a.c",
        "--- a/a.c",
        "+++ b/a.c",
        "@@ -1,2 +1,2 @@",
        "---",
        "+++counter;",
        " end",
        "\\ No newline at end of file",
        "diff --git a/b.md b/b.md",
        "--- a/b.md",
        "+++ b/b.md",
        "@@ -1 +1 @@",
        "-x",
        "+y",
      ].join("\n"),
    );
    expect(f!.hunks[0]!.lines.map((l) => [l.kind, l.text, l.old, l.new])).toEqual([
      ["del", "--", 1, null],
      ["add", "++counter;", null, 1],
      ["ctx", "end", 2, 2],
    ]);
    expect([f!.added, f!.removed]).toEqual([1, 1]);
  });

  it("builds the tree with folders first and counts what changed under each", async () => {
    const { buildTree } = await import("./kaiWork");
    const tree = buildTree([
      { path: "src/pay.py", status: "modified", size: 10 },
      { path: "src/util/a.py", status: "unchanged", size: 1 },
      { path: "README.md", status: "unchanged", size: 2 },
      { path: "src/new.py", status: "added", size: 3 },
    ]);
    expect(tree.children.map((c) => c.name)).toEqual(["src", "README.md"]);
    const src = tree.children[0]!;
    expect(src.children.map((c) => c.name)).toEqual(["util", "new.py", "pay.py"]);
    expect([tree.changed, src.changed, src.children[0]!.changed]).toEqual([2, 2, 0]);
  });

  it("pairs each command with its output, and keeps one without output", async () => {
    const { terminal } = await import("./kaiWork");
    expect(
      terminal([
        { kind: "tool", text: "Ran pytest -q", at, ref: "t1" },
        { kind: "tool", text: "Read a.py", at },
        { kind: "tool", text: "Ran ls", at, ref: "t2" },
        { kind: "output", text: "a.py", at, ref: "t2" },
        { kind: "output-error", text: "1 failed", at, ref: "t1" },
        { kind: "tool", text: "Ran make", at },
      ]),
    ).toEqual([
      { ref: "t1", command: "pytest -q", output: "1 failed", failed: true, at },
      { ref: "t2", command: "ls", output: "a.py", failed: false, at },
      { ref: null, command: "make", output: null, failed: false, at },
    ]);
  });
});
