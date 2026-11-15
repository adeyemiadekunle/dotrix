# Working in the Dotrix monorepo

Dotrix keeps applications and shared packages in one repository. Each application
has its own entry point, runtime configuration and deployment. Sharing a checkout
does not authorize importing another application's internals or sharing its secrets.

## Dependency boundaries

- `packages/engine` is the Python domain/runtime library. It cannot import either
  Python application, `apps`, FastAPI or Typer.
- `apps/backend` and `apps/cli` consume the engine; they cannot import one another.
  Backend integration tests may exercise the CLI, but runtime source may not.
- Browser apps consume public exports from `@dotrix/ui` and, where declared,
  `@dotrix/api-client`. Applications cannot import another application's source.
  A package cannot import an application. Relative cross-package imports and
  imports through another package's `/src` directory are rejected.
- Shared workspace dependencies must be declared in the consuming manifest.
  Build tooling can read package manifests or build artifacts across applications;
  it is outside the runtime-source import check.
- The backend Docker image contains CLI workspace metadata for uv resolution,
  but does not copy or install CLI runtime source.

Run `pnpm check:boundaries`. CI parses Python ASTs and TypeScript/JavaScript module
syntax, including literal dynamic imports and `require`. These are architecture
checks, not an OS security sandbox or a proof against computed imports/eval.

## Checks for affected applications

`scripts/affected.py` reads Node/Python manifests and follows reverse dependencies.
The desktop's bundled CLI is an explicit cross-language build dependency. It uses
all changes since the branch merge-base, including deleted files; it does not look
only at the last commit.

| Change | Selected work |
| --- | --- |
| Public site source | Site build/typecheck; no backend suite or web E2E |
| Web app source | Web build/typecheck/tests and browser E2E |
| Shared UI | UI, web, admin and site; web E2E |
| API client/schema | API contract regeneration, its browser consumers, web E2E |
| Backend | Backend tests/migrations, API contract regeneration and web E2E |
| CLI | CLI tests/install smoke checks and desktop packaging |
| Python engine | Engine, backend, CLI and desktop; contract and web E2E |
| pnpm/shared Node config | All Node workspaces and web E2E |
| uv/shared Python config | All Python workspaces and the bundled desktop CLI |
| Docs only | Format/lint, architecture/tooling guards and release validation |
| Workflow/tooling/unknown source or missing Git history | Full selection |

Examples:

```bash
pnpm ci:affected --base origin/stage --head HEAD
python scripts/affected.py --all
pnpm build:web
pnpm build:desktop
pnpm test:tooling
```

CI always emits `checks`, including for docs-only PRs. It fails if detection or
any selected job fails or is cancelled. A deliberately unselected app job may be
skipped. The desktop workflow similarly emits `desktop-checks` and uses the same
selector, so engine changes cannot silently miss the bundled CLI installer.
Configure branch protection to require these stable aggregate checks plus
`release-flow`; no repository settings are changed by this implementation.

Builds still use Turborepo's dependency ordering/cache. Relevant public build
variables and app-local dotenv inputs participate in build hashes; server/model
credentials are not passed to build tasks. Changing a package without a declared
workspace dependency is an architecture error, not a reason to add an implicit CI
edge. Backend behavior additionally selects web E2E because those tests exercise
its HTTP contract.

## Separate versions and release artifacts

Release groups are independent:

| Group | Versioned files | Notes | Tag / delivery |
| --- | --- | --- | --- |
| Platform | Backend, engine, web, admin, site, UI, API client and `API_VERSION` | Root `CHANGELOG.md` | `platform-vX.Y.Z`; application deployments remain explicit |
| Desktop | `apps/desktop/package.json` | `apps/desktop/CHANGELOG.md` | `vX.Y.Z`; Windows installer and desktop update feed |
| CLI | `apps/cli/pyproject.toml` | `apps/cli/CHANGELOG.md` | `cli-vX.Y.Z`; standalone Windows CLI archive |

The platform group's internal versions remain aligned for now. Desktop and CLI
can advance without changing platform/API versions or each other's version.
The desktop still bundles the CLI from its release commit, with that CLI's own
version. Test compatibility before deploying an API-breaking platform release or
publishing clients against a separately deployed server.

Write the relevant component's Unreleased notes, then:

```bash
python scripts/release.py bump 0.2.1 --component desktop
python scripts/release.py bump 0.2.1 --component cli
python scripts/release.py bump 0.3.0 --component platform
python scripts/release.py check
python scripts/release.py plan
```

Each bump affects only that group. Python group bumps update `uv.lock`; platform
bumps also require `pnpm openapi`. Open a PR into `stage`, then merge `stage` into
`main` through the existing human release process. Main publishes only component
versions that do not already have tags. The legacy coordinated `v0.2.0` tag, if
present, is recognized without republishing it under new component names.

Desktop keeps the existing `v` tag format for updater compatibility. CLI/platform
releases explicitly use `--latest=false`, so they cannot replace the desktop
update feed. Desktop's bundled and development What's new views read its own
changelog, not unrelated server release notes.

The release workflow explicitly calls the reusable desktop/CLI builder: a release
created with `GITHUB_TOKEN` does not itself trigger another workflow's release
event. Desktop and CLI use distinct artifact names; retries can rebuild assets
for component tags at the same release commit. No server/cloud credentials are
inherited by those builds. `DOTRIX_APP_URL` is a public repository variable.

Desktop and CLI builds can also be run manually. Select the artifact and optionally
an existing matching component release tag to rebuild/attach its assets. With no
tag, the workflow only produces build artifacts. Publication validates tag/version
agreement and requires the public app URL. Windows x64 remains the configured
release target; these changes do not add macOS/Linux installers or signing.

The coding image workflow is independent and manual. Build-only is the default;
publication must be selected explicitly, uses a `sha-<commit>` image tag and the
`coding-image` environment's registry configuration/credentials. It never publishes
as a side effect of a desktop/CLI release or updates a mutable `latest` tag. Move
registry credentials into that GitHub environment and set its protections as
appropriate; this implementation does not move actual secrets or change settings.

## Configuration and credentials by application

| Scope | Configuration | Secret handling |
| --- | --- | --- |
| Local Docker infrastructure | Root `.env` from `.env.example` | Database/storage service credentials; never a browser build input |
| Backend API/worker/migrations | `apps/backend/.env` from its example; environment variables override | JWT, encryption and integration credentials stay server-side |
| Web/admin/site | Each app's `.env.local` from its own example | `VITE_*` is public; proxy targets are configuration, not sign-ins |
| Desktop | Explicit process/CI `DOTRIX_WEB_URL` | URL is public; sign-ins live in the OS keychain/runtime, not build.json |
| CLI | Explicit process/CI environment and `dotrix login` | Platform token in OS keychain; automation injects its own scoped token |
| Coding image publication | GitHub `coding-image` environment | Registry credentials only in the publication steps |

The backend never loads a dotenv file from an arbitrary current directory. If its
app-local file exists, it is exclusive: missing values do not fall through to the
legacy root file. Without it, root `.env` remains a migration fallback. CLI and
desktop do not automatically load the example dotenv files; those document their
process variables. Vite is explicitly rooted at each app, even when invoked from
the repository root. Docker contexts already exclude all real dotenv/private-key
files; examples are allowed.

For native development, copy the backend and relevant frontend examples and set
real local values. Restart the API/worker after switching dotenv files. Keep backend database/storage credentials consistent with the
local services. For Docker app services, set
`DOTRIX_BACKEND_ENV_FILE=./apps/backend/.env` in root `.env` when adopting the split;
the default preserves the legacy single-file development setup. Container addresses
remain supplied by Compose. Do not put backend/provider/signing keys in frontend
files, `VITE_*`, desktop resources or committed examples.

## Update one local application

After the shared stack is started with `pnpm docker:up`:

```bash
pnpm docker:web
pnpm docker:admin
pnpm docker:site
pnpm docker:backend
python scripts/update_local.py backend --dry-run
```

Frontend updates use `--no-deps`, so they do not restart the API or worker. Backend
updates build the backend image, apply migrations first, then recreate only API and
worker. They do not rebuild the coding image or restart storage/database/browser
apps. These commands address the local development Compose stack, not Dokploy.
Production rollout, environment secrets, branch protection and image publication
remain operator actions; no deployment or release is performed by these checks.
