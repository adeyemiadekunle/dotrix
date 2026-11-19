// What's new reads the bundled CHANGELOG.md (node --test, after tsc).
import assert from "node:assert/strict";
import { test } from "node:test";

import { parseChangelog } from "./changelog";

const TEXT = `# Changelog

Intro text.

## [Unreleased]

### Added

- Something not out yet.

## [0.2.0] - 2026-11-03

### Added

- The desktop app installs updates: it says when one is ready,
  and restarts into it.
- \`dotrix codes\` in the terminal.

### Fixed

- A fix.

### Removed

## [0.1.0] - 2026-10-31

### Added

- The first release.
`;

test("releases newest first, with their sections and items", () => {
  const releases = parseChangelog(TEXT);
  assert.deepEqual(
    releases.map((r) => [r.version, r.date]),
    [
      ["0.2.0", "2026-11-03"],
      ["0.1.0", "2026-10-31"],
    ],
  );
  assert.deepEqual(releases[0]!.sections, [
    { title: "Added", items: ["The desktop app installs updates: it says when one is ready, and restarts into it.", "`dotrix codes` in the terminal."] },
    { title: "Fixed", items: ["A fix."] },
  ]);
});

test("Unreleased only when asked for (a development build)", () => {
  assert.equal(parseChangelog(TEXT, { unreleased: true })[0]!.version, "Unreleased");
  assert.deepEqual(parseChangelog("no releases here"), []);
});
