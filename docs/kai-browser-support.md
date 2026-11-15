# Kai's browser connections

The Browser pane and the tools that drive a browser are separate connections.

| Coding engine | Cloud sandbox: headless browser and screenshots | Desktop local runner: app's Browser pane |
| --- | --- | --- |
| Claude Code | Connected | Connected |
| Codex | Connected | Connected |
| OpenCode | Connected | Connected |
| fx | Connected | Linux Bubblewrap, fx 0.0.17 and custom API-key connection required |

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
separate work.

Native Codex requires 0.169.0 or newer. Its launcher disables existing MCP servers,
hooks and plugins before adding a fresh app-owned browser connection. Commands
use its workspace-write OS sandbox with networking disabled; the browser has its
own authenticated connection. The bearer token never appears in the command line.

Native Claude Code shell support requires exactly **2.1.296**, Linux Bubblewrap
with working user/network namespaces, system Python/Bash/Git, and a personal
`ANTHROPIC_API_KEY`. Optional `ANTHROPIC_BASE_URL` must be HTTPS or loopback HTTP;
The admitted coding-session model takes precedence over local preferences; direct
internal probes use `ANTHROPIC_MODEL` or `claude-sonnet-4-6`. The host pins this endpoint/model
and injects the API key on Messages/count-token requests only. The runtime receives
a placeholder key, a temporary home and the authenticated Browser relay. Its
original settings, hooks, OAuth files, plugins and unrelated MCP servers are absent.
Proxy and CA settings are available to the host relay, not the guest shell.

The entire Claude process and its descendants run in the same Linux namespace
boundary used for fx. Only the disposable worktree, private profile and scratch
space are writable. Git uses an isolated baseline/index with no original remotes,
hooks or credential helpers. Source Git metadata is hidden. The built-in Bash
sandbox is disabled inside this stronger process boundary; a tool's
`dangerouslyDisableSandbox` flag cannot remove the outer namespace. Direct
networking is unavailable; the model and authenticated Browser are fixed host
relay services. Browser user controls remain enforced by the desktop MCP server.
No permission flag enables an unconfined host shell.

Claude's built-in sandbox alone was also probed but did not hide sibling files
under the host's `/tmp`, so it is not this adapter's boundary. There is no `socat`
requirement for the full-process relay. Unsupported hosts and subscription/OAuth
logins retain file-only execution (or use local `sbx`); an API-key namespace
startup/version failure stops the turn. To choose this path when `sbx` is installed,
use `dotrix runner --tool claude-code --isolation none --project /path/to/checkout`.
`none` here disables `sbx`; the native namespace remains required for commands.

Native fx requires exactly 0.0.17, Linux, Bubblewrap with working user/network
namespaces, system Python, Bash and Git, and a custom OpenAI Chat Completions
API-key connection configured in the person's fx settings. The configured model
must match the coding session. OAuth/gateway sign-ins and other operating systems
remain unavailable. Unsupported hosts fail closed; there is no unconfined fallback
or environment-variable bypass. fx 0.0.17's interactive agent profiles are not an
ACP policy boundary (`fx acp` does not accept `--profile`).

The entire runtime and its shell descendants run inside a private namespace.
Only the disposable worktree and temporary model profile are writable, with
private scratch space and read-only system tools. Git uses an isolated baseline
and index; the source checkout's Git metadata, remotes and hooks are hidden.
Direct networking is unavailable. A host relay forwards only the pinned model
endpoint and authenticated desktop Browser connection, injecting credentials
outside the namespace. The model sees a placeholder API key. Copied OAuth files
are removed and credential write-back is disabled. Temporary profiles are removed
by the runner. The Browser pane's existing user controls still apply at its host.

Shell execution is allowed within that boundary. Built-in web fetch cannot reach
external hosts; web access goes through the authenticated Browser transport.
Unknown ACP permissions and outside-worktree file permissions remain refused.
Stop terminates the namespace, including background commands. A provider recovery
that needs user input or fails ends the turn as failed, preventing publication.
There is no fx Docker Sandboxes template. Windows and live `sbx` verification remain
open.

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

The native-runner tests use real Claude Code/Codex/fx binaries, scripted local model endpoints
and the desktop's actual authenticated MCP transport. They check browser calls,
worktree writes, refused outside writes, isolated shell commands and cleanup. They
do not establish real-model adoption or an actual Electron page interaction.

```bash
DOTRIX_TEST_CODEX=/path/to/codex DOTRIX_TEST_FX=/path/to/fx \
uv run pytest apps/cli/tests/test_real_local_engines.py -q
```

### NVIDIA live validation (2026-11-14)

The NVIDIA models endpoint listed `nvidia/nemotron-3-ultra-550b-a55b`, and real
requests succeeded. Native fx 0.0.16 used `read_file` and `edit_file` to fix a
small disposable Python bug; independent positive, mixed-sign and zero checks
passed. Outside-worktree reads and writes returned permission denials. Shell
execution was absent from the offered tools; the model instead wrote an unused
script inside the disposable worktree, so this is not evidence of a shell-call
permission denial.

The public `web_fetch` probe returned `NetworkUnreachable`, rather than an explicit
permission denial. A loopback probe was rejected by fx's public-URL restriction.
These results do **not** establish the local runner's intended blanket web-fetch
refusal; that boundary remains unverified on an externally reachable host.

Real fx turns through `LocalRunner` also verified that an injected provider HTTP
401 after an actual edit reports `failed`, and a simulated platform Stop after an
actual edit reports `stopped`. Neither publishes a patch; the source checkout
remains unchanged and temporary fx profiles are removed. The model requests were
live; the platform transport and failure injection were test doubles.

This managed environment requires an outbound HTTP proxy. Native fx's live
requests used a localhost transport relay to the real NVIDIA endpoint; the relay
did not generate model responses. Docker's direct outbound connection failed,
which prevents the stock sandbox egress proxy from reaching NVIDIA here. This
is separate from deployed cloud validation. The pinned image built, but the cloud
OpenCode attempt failed before engine startup when Docker ran out of disk space;
the fx case then failed during fixture setup for the same reason. The disposable
image and build caches were removed to recover space. No cloud model or browser
success is established by these attempts. There was no actual Electron desktop
session, so Browser-pane interaction, its user controls and desktop Stop remain
unverified. Provider token counts are usage evidence, not proof of billed cost.

### fx 0.0.17 follow-up (2026-11-15)

The checksummed real binary passed 12 namespace tests with scripted model
responses: reads/edits, hidden sibling files, shell writes inside the worktree,
blocked direct fetch, authenticated Browser MCP transport, isolated Git worktree
metadata, protected credential metadata, Stop killing a background command, and
provider failure after an edit. The real Node cloud driver and fx also completed
a new turn and resumed session inside Bubblewrap; this is protocol evidence,
not a deployed Docker cloud test. Its provider forwarder now uses stable sandbox
loopback port 31821 because fx 0.0.17 refuses resume after a base-URL change.

A separate real NVIDIA request used `nvidia/nemotron-3-ultra-550b-a55b` through
the native namespace relay. It read the code and test, changed subtraction to
addition, and ran `python3 -B -m unittest -v test_add`. Its first shell call omitted
the required action and was rejected without execution; the model corrected it.
The test and independent verification passed positive, mixed-sign and zero cases.
The original profile was unchanged and the temporary profile was removed.
fx reported 20,751 input tokens, 522 output tokens, 4,384 cache-read tokens and
169 reasoning tokens. These are runtime counters; uncached/raw provider accounting
and actual billed cost were not independently available.

The coding image source now pins fx 0.0.17; it has not been rebuilt or deployed by
these checks. Nova's separate libfx chat host remains pinned to 0.0.16. Actual
cloud NVIDIA/OpenCode browser runs and Electron Browser-pane controls still need
live validation. No test PR was pushed and no deployment settings were changed.

### Claude Code native commands (2026-11-15)

Seven real Claude Code 2.1.296 cases passed against a scripted Anthropic endpoint:
read/edit followed by meaningful positive/mixed-sign unit tests, hidden host files
and blocked sibling writes/networking, isolated Git diff, an inner-sandbox bypass
attempt that cannot bypass the outer namespace, provider failure after an edit,
Stop killing a background shell, and the desktop's authenticated Browser MCP
transport. The source checkout and original Git pointer remained unchanged.
The existing twelve fx/cloud-driver namespace cases also passed after sharing the
relay. These are real-binary/OS-boundary tests with synthetic provider responses;
no paid Claude model, packaged Electron or Windows/macOS shell test is claimed.
OAuth credential relaying is not implemented. CLI status messages no longer say
all native engines run no commands.
