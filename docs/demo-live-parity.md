# Demo and live parity

Demo and signed-in workspaces share presentation components; their data and available actions differ deliberately.

| Area | Shared presentation | Data and behaviour |
| --- | --- | --- |
| Workspace navigation | Studio and Shell | Demo uses seed data; live loads workspace-scoped queries. Missing model keys preserve navigation. |
| Home and Projects | Same screens and styles | Fresh accounts show real empty states rather than seeded projects/tasks. |
| Typography | Shared CSS and bundled fonts | Geist Sans/Mono, including the previous sans-serif title weights and spacing. |
| Chat | Project groups, ThreadRow and Message | Demo reads seeded threads/history; live supports streaming, approvals, delegation and steering. |
| Codes | SessionRow and Message | Sample adaptation preserves issue/project, status, turn count and PR metadata. Links open Codes directly. |
| Coding panes | PanelFrame, ChangeList, FileTree and CommandList | Demo shows recorded aggregate diffs, paths and commands. Missing contents/reviews are stated explicitly; live uses actual worktree/run data. |
| Settings | RulesEditor and GitHubContent | Sample edits are local; sample connections are read-only. Live saves use current permissions and real workspace/provider endpoints. |
| Onboarding | Auth-card typography and controls | Real setup saves a first project, offers GitHub and personal models, then opens the project. Signed-out visitors sign in rather than complete a fake questionnaire. |

## Onboarding

Default signup enters Project → GitHub → Model → Start working. The personal workspace is reused; team-workspace creation is explicit. A project must be saved before setup can complete. Documents-only projects and model setup later are supported. Confirmed workspace/project IDs survive refresh and GitHub redirects. Personal keys are cleared after saving and never written to the URL or browser storage. Key storage does not imply a paid model call was verified.

## Verification

Unit tests cover seed adaptation, orphaned references, unchanged source data and direct Codes links. Browser tests cover populated sample conversations and coding panes without workspace API requests, typography, sample/live session isolation, actual signup and project creation/retry against a disposable backend, saved setup across refresh, encrypted personal-key storage, GitHub return destinations, and live Settings/model-gate behaviour. GitHub installation metadata/redirects are simulated; no external installation or paid model call is performed. Production accounts and deployment are not exercised by these tests.

Sample history is read-only and intentionally lacks live execution controls. Different counts, empty states and permission-dependent actions are expected; they must not be replaced with fabricated seed data in a real account.
