// The desktop app's link rules (node --test, after tsc).
import assert from "node:assert/strict";
import { test } from "node:test";

import { opensOutside, staysInside } from "./links";

test("only web and email links open outside the app", () => {
  for (const url of ["https://example.com", "http://localhost:3000", "http://127.0.0.1:8000/x", "mailto:a@b.c"]) assert.equal(opensOutside(url), true, url);
  for (const url of ["http://example.com", "file:///etc/passwd", "smb://host/share", "ms-msdt:/id", "javascript:alert(1)", "vscode://x", "not a url", ""])
    assert.equal(opensOutside(url), false, url);
});

test("the window stays on the app and GitHub's sign-in pages", () => {
  const app = "https://app.dotrix.cc/w/x";
  for (const url of [
    "https://app.dotrix.cc/",
    "https://app.dotrix.cc/api/github/setup?code=1",
    "https://github.com/login/oauth/authorize?client_id=1&state=2",
    "https://github.com/login?return_to=%2Flogin%2Foauth",
    "https://github.com/sessions/two-factor",
    "https://github.com/apps/dotrix/installations/new?state=1",
    "https://github.com/settings/installations/123",
  ])
    assert.equal(staysInside(url, app), true, url);
  for (const url of [
    "https://evil.example/",
    "http://app.dotrix.cc/",
    "https://github.com/someone/repo",
    "https://github.com/loginx",
    "https://github.com.evil.example/login",
    "https://github.com:444/login",
    "file:///etc/passwd",
    "nonsense",
  ])
    assert.equal(staysInside(url, app), false, url);
});
