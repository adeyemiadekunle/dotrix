import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { inspect } from "../check-boundaries.mjs";

const base = path.resolve("/repo");
const app = { folder: path.join(base, "apps/web"), kind: "apps", name: "@dotrix/web", dependencies: { "@dotrix/ui": "workspace:*" } };
const ui = { folder: path.join(base, "packages/ui"), kind: "packages", name: "@dotrix/ui" };
const desktop = { folder: path.join(base, "apps/desktop"), kind: "apps", name: "@dotrix/desktop" };
const filename = path.join(app.folder, "src/index.ts");
const packages = [app, ui, desktop];

test("shared packages need declared public imports", () => {
  assert.deepEqual(inspect('import { Button } from "@dotrix/ui/components/button";', filename, app, packages), []);
  assert.equal(inspect('import("../../../packages/ui/src/astryx")', filename, app, packages).length, 1);
  assert.equal(inspect('export * from "@dotrix/ui/src/private";', filename, app, packages).length, 1);
  assert.equal(inspect('import "@dotrix/ui";', filename, { ...app, dependencies: {} }, packages).length, 1);
});

test("apps cannot import other apps, including Python app files", () => {
  for (const source of ['require("@dotrix/desktop")', 'import("../../desktop/src/main")', 'export * from "../../backend/private.json"']) {
    assert.equal(inspect(source, filename, app, packages).length, 1);
  }
  assert.equal(inspect('import x from "../../apps/web/src/main";', path.join(ui.folder, "index.ts"), ui, packages).length, 1);
});

test("comments and quoted source code are not imports", () => {
  assert.deepEqual(inspect('// import "@dotrix/desktop";\nconst text = \'require("@dotrix/desktop")\';', filename, app, packages), []);
});
