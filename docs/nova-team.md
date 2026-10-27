# Nova and the built-in team

Nova is the lead adviser in interactive conversations. The fixed team is Nova, Lyra,
Orion, Vega, Juno, Echo, and Kai. Built-in identities and role instructions are code;
workspace, project, and personal guidance are additional, versioned instructions.
Custom agent identities are retired, while their historical records remain attributable.

## Configuration and rollout

Enable `DOTRIX_DURABLE_DELEGATION=true` for a pilot. It gates creation of new task trees,
not recovery of trees already recorded. Use `DOTRIX_JOBS=worker` for durable queue
publication and lease recovery after a process restart. The migration archives custom
definitions, disables their automations with a reason, rejects their pending approvals,
and fences unfinished custom runs; it retains their historical records.

The six thinking-agent contracts are listed by the existing agents API. The shared
`agent-team` API includes Kai as the seventh identity. Workspace and project owners or
administrators can add guidance and restrict the core role's tools and policies; personal
preferences are private and their revision history includes resets. Guidance does not
grant permissions or override the role, work mode, or approval controls.

## Task and coding behavior

Nova sends one batch of specialist briefs with task keys and dependencies. Each child
has its own checkpoint, inherited requester and policy, and a persisted structured
result. Two independent analysis tasks can run together; changing specialist tasks are
serialized. Failed or partial prerequisites block their dependants. The parent waits
without occupying a worker and resumes when the batch settles. Native framework
delegation is unavailable in platform conversations. Cross-project conversations remain
read-only and do not launch specialist tasks.

Only an instructed Build request starts Kai from a conversation. A completed changed
turn links a read-only Juno review to its coding turn and revision. Nova's automatic
summary waits for any active conversation turn, then reports the saved outcome and
review without a fabricated user message or further coding. `changes_ready` and
`recovery_required` remain visible and require their existing acceptance or recovery
flows; Stop preserves those pending changes. Review evidence distinguishes reported
checks from independently verified results. Later changed turns supersede older reviews.

The private agent activity API and the agent panel show specialist and Kai activity.
Coding and Review share the resizable side area; Juno's panel has Summary, Findings, and
Evidence views. Stronger review methods can extend the existing structured findings and
evidence contract without changing the panel's meaning.
