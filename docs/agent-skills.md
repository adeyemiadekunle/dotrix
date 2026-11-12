# Agent skills and tool capabilities

A skill supplies a procedure within the agent's existing permissions. It cannot install tools,
grant credentials, change approval policy, or allow writes in Plan mode.

## Referenced resources

A project skill at `agent-rules/skills/team-check.md` may declare:

```markdown
Description: Check a change against the team checklist.
Agents: project-manager, coding, reviewer
Resources: references/checklist.md, templates/report.md
Requires: repository.read, terminal

Read references/checklist.md before reviewing the change.
```

Store those resource files at:

- `agent-rules/skills/team-check/references/checklist.md`
- `agent-rules/skills/team-check/templates/report.md`

These are project knowledge files, managed through the existing human knowledge editor/API.
Workspace skills can reference resources supplied by each project under the same convention.
Only explicitly declared resources are included. Missing files are reported, not fetched from
another project or the network. Paths must be relative, with no traversal; each skill may
reference at most 20 resources. The complete catalog, including resources, is capped at 256 KB.
Resource documents are not themselves listed as skills. Script source can be stored as text;
loading it does not execute it or grant permission to execute it.

A run pins resource text and SHA-256 hashes alongside its skill text. Specialists inherit their
parent's snapshot. Changes to project resources affect new runs, not retries of an existing run.
In chat, use `read_skill(skill="team-check", resource="references/checklist.md")`.
In cloud coding, the runtime receives paths to pinned files outside the repository and reads
only the relevant procedures and resources. Every worker uses the same run snapshot. Local
computer turns retain inline skill/resource content for compatibility.

## Tool requirements

`Requires:` is optional advisory metadata. Coding currently reports these capabilities:
`repository.read`, `repository.write`, `terminal`, `browser`, and `publication`.
Unknown requirements remain unavailable. Plan mode reports repository writes and browser access
as unavailable; terminal commands remain subject to its read-only filesystem boundary.
Agents never publish directly: publication belongs to Dotrix's approval flow.

Codes → session details → Tools and skills shows the capabilities offered for the turn,
pinned skill versions, available reference paths, missing resources and unavailable required
tools. Runtime briefs receive the same warnings. Capability descriptions do not prove that
a deployed sandbox, provider credential or external service is healthy; runtime checks still
apply. Paid-engine and deployed read-only compatibility checks remain separate validation work.


## Runtime validation

The opt-in `test_live_kai_loads_a_pinned_skill_resource` test runs against Claude Code, Codex,
OpenCode and fx in the coding image. It asks the agent to use a marker present only in a pinned
reference file and verifies the resulting code. Run it with the appropriate personal test key,
a built `dotrix-coding:latest` image and the test database configured:

```bash
uv run pytest apps/backend/tests/integration/test_live_coding.py -k loads_a_pinned_skill_resource -v
```

Provider keys use `DOTRIX_LIVE_ANTHROPIC_API_KEY` and `DOTRIX_LIVE_OPENAI_API_KEY` as in the
existing live tests. These tests make paid model calls; GitHub is simulated and the repositories
are disposable local fixtures. Missing keys or coding image skip the affected cases. A skipped
case is not evidence that its runtime works.
