"""Skills (agents v2 step 2): reusable procedures an agent loads when the work calls for one,
`SKILL.md`-style: a name (the file's), a one-line description, the agents it's for, and the steps.

A skill's "When:" line lists words that, found in an issue, put the skill in Kai's brief (one
without the line is always included); chat agents read skills when they choose, so it's Kai's only.
A skill's "Agents:" line names the roles (agent-rules file names: architecture, reviewer, coding,
…) whose prompt lists it; a skill without one is listed for every agent. Kai can't read skills
from the sandbox, so its brief carries its own skills in full (`skills_for("coding")`).

Every new project gets these in `agent-rules/skills/`; owners and admins edit them or add their
own there like any rule. A run's prompt lists each skill with its description only, so a skill
costs a line until an agent reads it.
"""
from __future__ import annotations

import re

SKILLS_FOLDER = "agent-rules/skills/"
_DESCRIPTION = re.compile(r"^description\s*:\s*(.+)$", re.IGNORECASE)
_AGENTS = re.compile(r"^agents\s*:\s*(.+)$", re.IGNORECASE)
_WHEN = re.compile(r"^when\s*:\s*(.+)$", re.IGNORECASE)

# What every change of Kai's has to meet before it's done, and what Juno checks it against.
DEFINITION_OF_DONE = """## Definition of done
A change is done when all of these hold; say how each was checked, or why it couldn't be:
1. Tests cover the behaviour the issue asks for (a new or changed test fails without the change),
   and the project's tests pass.
2. The project's lint and type checks were run, and their results are reported.
3. A database migration can be rolled back (a working downgrade, or why it can't be, said), and
   doesn't lock a large table while it runs.
4. No secrets, keys, tokens, or personal data in code, tests, fixtures, or logs.
5. Errors are handled: failures return a clear error, aren't swallowed, and don't leak internals.
6. Only what the issue needs changed, in the code's own style.
"""

SKILLS: dict[str, str] = {
    "write-an-adr": """# Skill: write an ADR
Description: Record an architecture decision so it can be followed and later superseded.
Agents: architecture, documentation, project-manager

## Steps
1. Search decisions/ for an ADR on the same question; if one exists, the new ADR supersedes it.
2. Read the requirements and the architecture it touches, and check `graph_impact` on them.
3. Follow /dotrix/agent-rules/templates/decisions.md: context, the decision, the options with
   their trade-offs, the consequences, "Affected modules", and "Supersedes" when it replaces one.
4. Name it decisions/ADR-NNN.md with the next number.
5. Propose tasks for the work it implies, linked to the ADR.
""",
    "triage-a-bug": """# Skill: triage a bug report
Description: Turn a report into a well-formed bug, or a comment on the issue it duplicates.
Agents: project-manager, product, reviewer

## Steps
1. Restate the report: what happened, what was expected, where, and since when.
2. Look for duplicates with search_knowledge and list_issues (open bugs first).
3. If one matches, propose a comment on it with what's new in this report; stop there.
4. Otherwise propose a bug: a title that names the symptom, steps to reproduce, expected and
   actual behaviour, priority by impact (who is blocked, how many), and links to the
   requirement or module it concerns.
""",
    "scope-a-failing-build": """# Skill: scope a failing build
Description: Work out what broke a build or a test run, and who should look at it.
Agents: reviewer, architecture, project-manager

## Steps
1. Read the failure: the first error, not the last; note the file, test, and message.
2. Find what changed: the commit or PR, and the files it touched (code_search, code_read).
3. Check `graph_impact` on the modules and requirements those files belong to.
4. Decide: a real regression, a flaky test (only with evidence it passed on the same commit),
   or the environment.
5. Report one finding with the cause, the evidence, the files, and a suggested fix.
""",
    "repository-knowledge": """# Skill: explain the repository
Description: Turn the connected repository into sourced wiki pages, domain by domain, with its gaps.
Agents: documentation

## Steps
1. `repo_stale_pages` first: update pages whose cited code changed. Then `repo_coverage`: the
   domains with paths still to read; take a few per run.
2. For each, `repo_paths(domain)` lists them; read the telling ones, and `repo_mark_read` as you go.
   Dependencies come from `repo_dependencies` (declared and locked versions), not raw lockfiles.
3. Write docs/wiki/<domain>.md: each claim cited as `path:line`, with its basis: (observed),
   (declared: <document>), (inferred), or (unknown). Code behaviour isn't a requirement unless a
   document says so.
4. End each page with its gaps and questions, and whom to ask; keep people's edits.
5. `repo_check_page` on the draft before you write it: every citation must resolve.
""",
    "break-down-a-feature": """# Skill: break a feature into stories
Description: Turn a requirement into an epic and stories a coding agent can work from.
Agents: product, project-manager

## Steps
1. Read the requirement in full and the decisions it links to.
2. Split by user-visible outcome, not by layer: each story delivers something someone can try.
3. Give each story acceptance criteria (testable, one behaviour each) and link the requirement.
4. Order them with depends_on; put open questions in the epic, not the stories.
5. Propose the epic and stories as one batch for approval.
""",
    "threat-model-a-feature": """# Skill: threat-model a feature
Description: Find how a feature could be abused before it's built (STRIDE), and what has to stop it.
Agents: architecture, reviewer, coding
When: auth, login, sign-in, sign in, password, token, session, permission, role, access, tenant, workspace, upload, payment, webhook, secret, encrypt, admin, invite, oauth, public endpoint

## Steps
1. Draw the flow in words: who calls it, what data it takes and returns, where it's stored, which
   services it reaches. Mark each trust boundary (browser to API, API to database, to a third party,
   between workspaces or tenants).
2. List the data by sensitivity: secrets and tokens, personal data, another tenant's data, money.
3. Walk STRIDE across each boundary: Spoofing (who can pretend to be whom), Tampering (what input
   or stored data can be changed), Repudiation (what isn't audited), Information disclosure (what
   leaks, in responses, errors, or logs), Denial of service (what's unbounded: sizes, loops, retries,
   rate), Elevation of privilege (where a check is missing or done in the client).
4. Write abuse cases as sentences ("a member of workspace A reads workspace B's issue by its ID").
5. For each, the control that stops it and where it lives (a permission check on the route, a
   workspace filter in the query, a size limit), and the test that proves it.
6. Check the libraries involved with `dependency_advisories`.
7. Report: the flow, the boundaries, threats ranked by impact and likelihood, controls, and open risks.
""",
    "security-review": """# Skill: security review
Description: Review code or a design against an OWASP ASVS checklist; every finding with file, line, and fix.
Agents: reviewer, architecture, coding
When: auth, login, sign-in, sign in, password, token, session, cookie, csrf, permission, role, access, tenant, upload, file, payment, webhook, secret, key, encrypt, admin, invite, oauth, sql, query, input, form, redirect, url, rate limit, security, vulnerab, dependency, upgrade

## Check, in order
1. Authorization and tenant isolation: every route checks permission on the server; every query
   filters by the caller's workspace or project; IDs from the request are never trusted alone;
   a missing resource and a forbidden one look the same to outsiders (404).
2. Authentication and sessions: tokens are hashed or encrypted at rest, expire, and are revoked on
   sign-out; no credentials in URLs; cookie flags (HttpOnly, Secure, SameSite) and CSRF protection.
3. Injection: SQL through parameters or the ORM only; no shell, eval, template, or path built from
   input; file paths confined to their folder; HTML escaped on output.
4. Input validation: types, lengths, ranges, and formats checked at the boundary; uploads by size
   and type; unknown fields refused.
5. Secrets: none in code, tests, config committed, or logs; loaded from the environment or a secret
   store; `code_search` for keys, tokens, and passwords.
6. Rate limits and resource use: sign-in, sign-up, password reset, and expensive endpoints are
   limited; page sizes, request bodies, and loops are bounded.
7. Data in logs and errors: no tokens, passwords, or personal data logged; errors don't expose stack
   traces or internals.
8. Dependencies: `repo_dependencies`, then `dependency_advisories` for known vulnerabilities.
9. Outbound requests: no fetch of a URL the user controls without an allowlist (SSRF).

## Report
Each finding: severity (critical, high, medium, low), file and line, what's wrong, how it could be
exploited, and the fix. Say what you checked and found nothing in, too.
""",
    "design-an-api": """# Skill: design an API
Description: Design an HTTP API change: resources, errors, pagination, versioning, and idempotency.
Agents: architecture, reviewer, coding
When: api, endpoint, route, rest, http, request, response, webhook, pagination, graphql, openapi, status code

## Steps
1. Name the resources (nouns) and their relationships; one URL per resource, nested only for
   ownership (`/workspaces/{id}/projects/{id}`). Verbs are HTTP methods; actions that aren't CRUD are
   sub-resources (`POST .../runs/{id}/stop`).
2. Request and response schemas: separate create, update, and read shapes; required versus optional;
   never return internal or secret fields.
3. Errors: one format (RFC 9457 problem details), the status per case (400 invalid, 401, 403, 404,
   409 conflict, 422, 429 with Retry-After), and a stable error code.
4. Lists: cursor or page pagination with a maximum page size, a stable order, and filters.
5. Idempotency: PUT and DELETE are idempotent; a POST that creates or charges takes an idempotency key
   or a natural unique key; retries can't double-apply.
6. Versioning and compatibility: add fields, don't rename or remove them; a breaking change gets a new
   version or a deprecation window.
7. Security: who may call it (permission), what's scoped by tenant, rate limits, input limits.
8. Write it into architecture/ (the API section) and propose an ADR for anything new.
""",
    "plan-a-schema-change": """# Skill: plan a schema change
Description: Change a database schema without downtime: backward-compatible steps, backfill, rollback, locks.
Agents: architecture, reviewer, coding
When: migration, schema, table, column, index, database, db, sql, alembic, model, foreign key, backfill

## Steps
1. What changes, and every reader and writer of the affected tables (`code_search`, `graph_impact`).
2. Expand, then contract: add the new column or table first (nullable or with a default the database
   applies without a rewrite); deploy code that writes both; backfill; switch reads; only then drop
   the old one, in a later release.
3. Backfill in batches with a bound per batch, resumable, outside the migration's transaction on
   large tables.
4. Locks: on a large table, create indexes concurrently, add a NOT NULL or foreign key as NOT VALID
   then validate, avoid a full rewrite; set a lock timeout.
5. Rollback: every migration has a downgrade that works with the data written since, or says why it
   can't and what the way back is.
6. Tests: the migration up and down on a copy with data; the code against both schemas during the
   switch.
7. Write the plan as ordered steps, each with how to check it and how to undo it.
""",
    "review-a-backend-change": """# Skill: review a backend change
Description: Review server code for transactions, queries, retries, timeouts, logging, and tests.
Agents: reviewer, coding
When: api, endpoint, route, server, backend, service, worker, job, queue, database, query, migration, transaction, .py, .go, .rs, .java, .rb, .sql

## Check
1. Transactions: one unit of work commits once; no partial writes on failure; no external call
   (HTTP, email, queue) inside an open transaction unless it's an outbox.
2. Queries: no N+1 (a query in a loop); indexes for the new filters and orders; lists bounded;
   every query scoped by tenant.
3. Concurrency: races on read-then-write (use a unique constraint, a row lock, or a compare-and-set);
   background jobs safe to run twice.
4. External calls: a timeout on every one; retries only on retryable errors, with backoff and a limit;
   failures surfaced, not swallowed.
5. Errors: domain errors mapped to the right status once; no bare `except` that hides a failure.
6. Logging: structured, with request IDs; no secrets or personal data; enough to debug a failure.
7. Tests: the behaviour and its error paths, isolation between tenants, a migration up and down.
8. Then the definition of done.
""",
    "review-a-frontend-change": """# Skill: review a frontend change
Description: Review UI code for accessibility (WCAG), loading, empty and error states, performance, and secrets.
Agents: reviewer, coding
When: ui, page, screen, component, button, form, modal, dialog, layout, css, style, frontend, react, view, accessibility, a11y, .tsx, .jsx, .vue, .svelte, .css

## Check
1. Accessibility (WCAG 2.1 AA): every control is a real button or link, reachable and usable by
   keyboard, with a visible focus; labels on inputs and icon-only buttons; text and contrast readable;
   dialogs trap and return focus; changes announced to screen readers where they matter.
2. States: loading, empty, error, and success are each designed; a failed request says what happened
   and how to retry; nothing shows stale or another person's data after switching.
3. Forms: validation shown next to the field; submit disabled or guarded against double submits.
4. Performance: no request in a render loop; lists virtualised or paged when long; large
   dependencies justified; images sized.
5. Security: no secrets or tokens in the bundle, local storage, or URLs; HTML from users never
   injected unescaped; the server, not the client, enforces permissions.
6. Design system: the project's components, tokens, and copy style; light and dark both work.
7. Tests: the user flow that changed, at the level the project tests (unit or browser).
8. Then the definition of done.
""",
    "build-a-ui-change": """# Skill: build a UI change
Description: Build a frontend change with the project's design system, all its states, and a tested flow.
Agents: coding
When: ui, page, screen, component, button, form, modal, dialog, layout, css, style, frontend, react, view, design, accessibility, a11y, .tsx, .jsx, .vue, .svelte, .css

## Steps
1. Find the screen and the components it uses; reuse the design system's components, tokens, and
   helpers rather than new styles or raw colours.
2. Build every state: loading, empty, error, success; keyboard and screen-reader use; light and dark.
3. Keep data fetching in the project's data layer; show only the actions the person may take.
4. Write or update the test for the flow (unit, or a browser test where the project has them), and run
   the project's lint, type check, and tests.
5. Summarise the change with how it was checked, and what you couldn't check (e.g. no browser).
""",
    "definition-of-done": """# Skill: definition of done
Description: Check a change against the definition of done before calling it finished or approving it.
Agents: coding, reviewer

## Steps
For each item, say met, not met, or couldn't check (and why), with the evidence: the test that covers
it, the command run and its result, the file and line.
""" + DEFINITION_OF_DONE.replace("## Definition of done\n", "\n## The list\n"),
    "write-acceptance-criteria": """# Skill: write acceptance criteria
Description: Write testable acceptance criteria (Given/When/Then) with the non-functional ones Kai and Juno check.
Agents: product, project-manager

## Steps
1. One behaviour per criterion, in Given / When / Then: the starting state, the action, the
   observable result. No "should work well": something a test can check.
2. Cover the edges: empty input, the largest allowed, a duplicate, no permission, another tenant's
   data, the failure of a dependency.
3. Add the non-functional criteria that apply, each measurable:
   - Security: who may do it; what's refused for others (and returns 404 or 403).
   - Performance: the response time or size limit that matters to the person.
   - Accessibility: usable by keyboard and screen reader (WCAG 2.1 AA).
   - Data: what's kept, for how long, and what's audited.
4. Mark what's out of scope, and the open questions, separately from the criteria.
""",
    "evaluate-a-library": """# Skill: evaluate a library or vendor
Description: Weigh a library or vendor on licence, maintenance, security, and alternatives; end with an ADR proposal.
Agents: research, architecture

## Steps
1. What it's for, and the requirement it serves; what we'd use of it.
2. Licence: its name, and whether it fits the project (copyleft obligations, commercial terms).
3. Maintenance: latest release and its date, release cadence, open issues and how they're answered,
   number of maintainers, who funds it. Cite each from the source you read.
4. Security: past vulnerabilities (`dependency_advisories` for the version we'd use; its advisories
   page), how fast they were fixed, its own dependencies.
5. Fit: size, platforms, the APIs we'd call, lock-in and how hard it is to leave.
6. Two or three alternatives, including building it ourselves, on the same points.
7. Recommend one, with the trade-offs, and propose an ADR (write-an-adr) for the decision.
""",
    "write-a-runbook": """# Skill: write a runbook
Description: Write a runbook a person can follow under pressure: symptoms, checks, fixes, rollback, escalation.
Agents: documentation, architecture

## Steps
1. One runbook per situation (an alert, a failure, a routine task), named for what someone sees.
2. Symptoms: what tells you it's happening (the alert, the error, the dashboard).
3. Checks: the exact commands or screens, in order, each with what a good and a bad result look like.
4. Fixes: the steps for each cause found, smallest and safest first.
5. Rollback: how to undo each fix, and how to tell it worked.
6. Escalation: who to call and when; what to record afterwards.
7. Cite where each command or fact comes from (docs, the wiki, the code); mark what's unverified.
8. Save it under docs/runbooks/ and link it from the docs index.
""",
    "keep-the-wiki-fresh": """# Skill: keep the wiki fresh
Description: Refresh the repository wiki: stale pages first, then the gaps, every claim cited again.
Agents: documentation

## Steps
1. `repo_stale_pages`: the pages whose cited code changed, left the repository, or was never read.
   Refresh those before writing anything new.
2. For each, reread the changed sources and update only the claims they affect; keep people's edits.
3. Then `repo_coverage` for domains with no page or paths still to read (repository-knowledge).
4. `repo_check_page` before each write: every `path:line` must resolve.
5. Report what you refreshed, what's still stale, and the gaps that need a person.
""",
}


def default_skills() -> dict[str, str]:
    return {f"{SKILLS_FOLDER}{name}.md": text for name, text in SKILLS.items()}


def describe_skill(content: str) -> str:
    """A skill's one-line description: its "Description:" line, else its first sentence."""
    for line in content.splitlines():
        if (match := _DESCRIPTION.match(line.strip())) is not None:
            return match.group(1).strip()[:200]
    for line in content.splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:200]
    return ""


def skill_agents(content: str) -> frozenset[str] | None:
    """The roles a skill is for, from its "Agents:" line; None (every agent) without one."""
    for line in content.splitlines():
        if (match := _AGENTS.match(line.strip())) is not None:
            return frozenset(a.strip().lower() for a in match.group(1).split(",") if a.strip())
    return None


def skill_triggers(content: str) -> tuple[str, ...] | None:
    """The words in a skill's "When:" line; None (always) without one."""
    for line in content.splitlines():
        if (match := _WHEN.match(line.strip())) is not None:
            return tuple(w.strip().lower() for w in match.group(1).split(",") if w.strip())
    return None


def skill_matches(content: str, text: str) -> bool:
    """Whether `text` (an issue, a request) calls for this skill: any of its words, as a whole word
    (a word starting with "." matches a file extension; one ending in a letter can match its start,
    so "vulnerab" finds "vulnerability"). A skill without words always matches."""
    words = skill_triggers(content)
    if words is None:
        return True
    lowered = text.lower()
    for word in words:
        if word.startswith("."):
            if re.search(re.escape(word) + r"\b", lowered):
                return True
        elif re.search(r"(?<![a-z0-9])" + re.escape(word) + (r"" if len(word) >= 7 else r"(?![a-z0-9])"), lowered):
            return True
    return False


_DIFF_HEADERS = ("diff --git ", "index ", "--- ", "+++ ", "@@ ", "new file mode", "deleted file mode", "similarity index")


def review_skills(text: str, skills: dict[str, str] | None = None) -> list[str]:
    """The review skills a change calls for, from what it touched (`text`: its title, files, diff):
    the reviewer's skills whose "When:" words appear, the definition of done aside (always checked)."""
    found = skills if skills is not None else SKILLS
    # A diff's own header lines ("index 3f2a..9c1b", "diff --git") say nothing about the change.
    text = "\n".join(line for line in text.splitlines() if not line.startswith(_DIFF_HEADERS))
    return [name for name, content in sorted(found.items())
            if "reviewer" in (skill_agents(content) or ()) and skill_triggers(content) is not None
            and name != "definition-of-done" and skill_matches(content, text)]


def skills_for(skills: dict[str, str], role: str) -> dict[str, str]:
    """The skills `role` gets: those naming it, and those that name nobody."""
    return {name: text for name, text in skills.items() if (agents := skill_agents(text)) is None or role in agents}


def skill_name(path: str) -> str:
    return path.removeprefix(SKILLS_FOLDER).removesuffix(".md")


def skills_guide(skills: dict[str, str], heading: str = "## Skills") -> str:
    """The prompt's list of skills (name -> content): names and descriptions only. The
    project's and the workspace's together; a project's skill wins over the workspace's of the
    same name, so the caller merges them first."""
    if not skills:
        return ""
    lines = [heading, "Before doing one of these, read it with read_skill(skill) and follow its steps:"]
    for name, content in sorted(skills.items()):
        lines.append(f"- {name}: {describe_skill(content)}")
    return "\n".join(lines)
