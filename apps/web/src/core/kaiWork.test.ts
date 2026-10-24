import { describe, expect, it } from "vitest";

import { kaiWork } from "./kaiWork";

const at = "2026-10-24T12:00:00Z";

describe("kaiWork", () => {
  it("shows the latest turn's changes, every file by folder with its last turn, and the commands run", () => {
    const work = kaiWork([
      {
        turn: 1,
        files_changed: [
          { path: "src/payments.py", added: 3, removed: 1 },
          { path: "README.md", added: 1, removed: 0 },
        ],
        events: [
          { kind: "tool", text: "Read src/payments.py", at },
          { kind: "tool", text: "Ran pytest -q", at },
          { kind: "text", text: "Ran out of ideas", at },
        ],
      },
      {
        turn: 2,
        files_changed: [{ path: "src/payments.py", added: 2, removed: 2 }],
        events: [{ kind: "tool", text: "Ran ruff check src", at }],
      },
    ]);
    expect(work.latest).toEqual([{ path: "src/payments.py", added: 2, removed: 2, turn: 2 }]);
    expect(work.files).toBe(2);
    expect(work.folders.map(([folder, files]) => [folder, files.map((f) => `${f.path}@${f.turn}`)])).toEqual([
      [".", ["README.md@1"]],
      ["src", ["src/payments.py@2"]],
    ]);
    expect(work.commands.map((c) => `${c.turn} ${c.text}`)).toEqual(["1 pytest -q", "2 ruff check src"]);
  });

  it("is empty before a turn has run", () => {
    expect(kaiWork([])).toEqual({ latest: [], folders: [], files: 0, commands: [] });
  });
});
