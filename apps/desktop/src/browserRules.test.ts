// The Browser pane's rules (node --test, after tsc).
import assert from "node:assert/strict";
import { test } from "node:test";

import { browsable, CLEAN_PARTITION, KEPT_PARTITION, loopback, partitionFor, readSettings } from "./browserRules";

test("the pane loads web pages only", () => {
  for (const url of ["https://example.com/a?b=1", "http://localhost:3000", "http://127.0.0.1:5173/x", "http://192.168.1.4:8080"])
    assert.equal(browsable(url), true, url);
  for (const url of ["file:///etc/passwd", "javascript:alert(1)", "chrome://settings", "about:blank", "vscode://x", "data:text/html,hi", "not a url", ""])
    assert.equal(browsable(url), false, url);
});

test("cookies are kept on disk only when asked", () => {
  assert.equal(partitionFor(false), CLEAN_PARTITION);
  assert.equal(partitionFor(true), KEPT_PARTITION);
  assert.ok(KEPT_PARTITION.startsWith("persist:"));
  assert.ok(!CLEAN_PARTITION.startsWith("persist:"));
});

test("settings default to a clean profile", () => {
  assert.deepEqual(readSettings(null), { keepCookies: false, kaiAllowed: true });
  assert.deepEqual(readSettings("not json"), { keepCookies: false, kaiAllowed: true });
  assert.deepEqual(readSettings('{"keepCookies":"yes"}'), { keepCookies: false, kaiAllowed: true });
  assert.deepEqual(readSettings('{"keepCookies":true,"kaiAllowed":false}'), { keepCookies: true, kaiAllowed: false });
});

test("Kai's pages are on this computer only", () => {
  for (const url of ["http://localhost:3000", "http://127.0.0.1:5173/x", "http://app.localhost:8080", "http://[::1]:3000/", "https://localhost/"])
    assert.equal(loopback(url), true, url);
  for (const url of [
    "https://example.com",
    "http://192.168.1.4:8080",
    "http://localhost.evil.example",
    "http://127.0.0.1.evil.example",
    "http://evil.example/?localhost",
    "file:///etc/passwd",
    "nonsense",
  ])
    assert.equal(loopback(url), false, url);
});
