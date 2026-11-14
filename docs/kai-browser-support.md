# Kai's browser connections

The Browser pane and the tools that drive a browser are separate connections.

| Coding engine | Cloud sandbox: headless browser and screenshots | Desktop local runner: app's Browser pane |
| --- | --- | --- |
| Claude Code | Connected | Connected |
| Codex | Connected | Not a supported local runner |
| OpenCode | Connected | Connected |
| fx | Connected | Not a supported local runner |

Cloud browser tools are offered in Build turns inside the supported Docker or
OpenShell sandboxes, not in Plan mode or a process without those boundaries. All
four adapters supply the same pinned Playwright MCP server. It runs in
`/tmp/playwright` with `--ignore-roots`; screenshots stay outside the repository
and are collected by the existing screenshot-storage path. Existing sandbox
network rules apply. A configured capability does not prove browser health on a
particular deployment.

OpenCode 2.3.0 receives the server through its platform-owned configuration and
calls it from Code Mode, for example:

```javascript
await tools.browser.browser_navigate({ url: "http://localhost:8080" });
return await tools.browser.browser_snapshot({});
```

Read the snapshot before interacting: automatic navigation snapshots may be file
links. Playwright MCP 0.0.85 accepts `target` for click/type operations, including
the element reference from a snapshot. The current tool schema is authoritative.
OpenCode's structured nested-call metadata supplies the activity labels for
navigation, clicking, snapshots and screenshots, including errors. A failed MCP
startup produces a visible warning and lets the turn continue.

The desktop pane keeps its existing controls: browser enabled, Kai allowed,
per-runner authentication, per-session tabs, and navigation to this computer's dev
servers. Docker Sandboxes (`sbx`) turns do not connect to that pane because their
VM cannot reach its loopback server. A live view of the cloud browser is also
separate work; this change connects OpenCode to the existing headless tools.

## Verification

The ordinary adapter tests check configuration, capabilities, activity parsing and
startup failure. The optional real-engine test runs the exact pinned OpenCode and
Playwright MCP against a local scripted model endpoint and a real local web page.
It navigates, reads a snapshot, clicks by target, reads the changed page and saves
a PNG, then repeats on a resumed session. It also checks that repository MCP
configuration never starts and that screenshots do not land in the checkout.

```bash
DOTRIX_TEST_OPENCODE=/path/to/opencode \
DOTRIX_TEST_PLAYWRIGHT_MCP=/path/to/playwright-mcp \
DOTRIX_TEST_CHROMIUM=/path/to/chromium \
uv run pytest apps/backend/tests/unit/test_opencode_browser.py -q
```

The binaries can also be discovered on PATH. The test makes no paid model calls;
it establishes the engine/tool contract rather than a real model's willingness to
use the browser, or deployed container isolation.
