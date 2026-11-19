# Plan 005: Proving an inbox on an unverified account removes the credentials set before that

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat f477722..HEAD -- apps/backend/src/dotrix_backend/modules/auth apps/backend/src/dotrix_backend/modules/api_tokens`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S–M
- **Risk**: MED — changes sign-in behaviour for people who signed up with a password and never verified their email
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f477722`, 2026-11-11

> **Product decision embedded in this plan — the operator should confirm it
> before execution.** Today an existing test asserts the opposite behaviour on
> purpose (`test_links_an_existing_account_by_verified_email`: "The password
> still works too"). This plan changes that for **unverified** accounts only.
> If the operator has not confirmed, STOP and ask.

## Why this matters

Password sign-up creates a fully working account and session before the email
address is verified. Later, three other flows prove who really owns the inbox
and attach that proof to the existing account **without removing anything set
up before it**:

- GitHub sign-in links to the existing account with the same (GitHub-verified) email.
- A magic sign-in link signs the person in and marks the email verified.
- A password reset sets a new password and marks the email verified.

So anyone can sign up with someone else's email and a password of their
choosing. When the real owner later signs in with GitHub or a magic link, they
land in that pre-created account, and the earlier registrant can still sign in
with the password — and with any personal API token (`dtx_…`) they created,
which a password reset does not revoke either. This is the well-known
"account pre-hijacking" pattern.

After this plan: the first time an **unverified** account's inbox is proven
through one of those flows, the password set before verification is cleared,
every existing session is signed out, and every API token is revoked. Verified
accounts behave exactly as today.

## Current state

- `apps/backend/src/dotrix_backend/modules/auth/service.py` — `AuthService`:
  - `signup` (lines 69-87): creates the user with a password hash and returns tokens before verification.
  - `sign_in_with_magic_link` (lines 219-229).
  - `sign_in_with_github` (lines 233-275).
  - `reset_password` (lines 277-288).
  - `_issue_tokens` (line 310): creates a new session + refresh token.
- `apps/backend/src/dotrix_backend/modules/auth/repository.py:73-82` — `RefreshTokenRepository.revoke_all_for_user(user_id, now)`: "Sign out everywhere (browsers and apps; API tokens are separate)". It revokes refresh tokens and `AuthSession` rows; revoked sessions are rejected immediately (`api/deps.py:86`, `AuthSessionRepository.signed_out`).
- `apps/backend/src/dotrix_backend/modules/api_tokens/models.py:18-40` — `ApiToken` with `revoked_at`; `api_tokens/repository.py` — `ApiTokenRepository` (`add`, `get_by_hash`, `get_for_user`, `list_for_user`); `api_tokens/service.py:116-120` revokes one token by setting `token.revoked_at = token.revoked_at or _now()`.

`service.py:219-229` today:

```python
    async def sign_in_with_magic_link(self, token: str) -> TokenPair:
        """Exchange the emailed token for a session. It works once; following it also
        verifies the email address (the person proved they read that inbox)."""
        action = await self._consume(token, ActionTokenPurpose.MAGIC_LINK)
        user = await self.users.get(action.user_id)
        if user is None or not user.is_active:
            raise InvalidLink()
        user.email_verified_at = user.email_verified_at or _now()
        tokens = self._issue_tokens(user)
        await self.session.commit()
        return tokens
```

`service.py:251-275` today (the branch of `sign_in_with_github` taken when the
GitHub account is not linked yet):

```python
            user = await self.users.get_by_email(profile.verified_email)
            if user is None:
                ... # creates a new verified user with password_hash=None
            elif not user.is_active:
                raise Unauthorized("This account can't sign in")
            # GitHub verified the address, which proves the inbox as a link would.
            user.email_verified_at = user.email_verified_at or now
            self.oauth_accounts.add(
                OAuthAccount(
                    user_id=user.id, provider="github", provider_user_id=profile.id, login=profile.login, created_at=now
                )
            )
            ...
        tokens = self._issue_tokens(user)
        await self.session.commit()
        return tokens
```

`service.py:277-288` today:

```python
    async def reset_password(self, data: PasswordResetConfirm) -> None:
        action = await self._consume(data.token, ActionTokenPurpose.RESET_PASSWORD)
        user = await self.users.get(action.user_id)
        if user is None or not user.is_active:
            raise InvalidLink()
        now = _now()
        user.password_hash = security.hash_password(data.new_password)
        # Proving inbox access also verifies the email.
        user.email_verified_at = user.email_verified_at or now
        # Sign out everywhere: a reset usually means the old password is compromised.
        await self.refresh_tokens.revoke_all_for_user(user.id, now)
        await self.session.commit()
```

Accounts with no password already exist and are supported: `finish_email_signup`
(`service.py:196-217`) creates users with `password_hash=None` ("sign in by
link, or set one with 'Forgot password?'"). Check how `login` (`service.py:89+`)
handles `password_hash is None` before relying on it (Step 1).

Existing tests that encode today's behaviour:

- `apps/backend/tests/integration/test_github_sign_in.py:97-106`:

```python
async def test_links_an_existing_account_by_verified_email(db_client: AsyncClient, signup, github: FakeGitHub) -> None:
    ada = await signup()
    assert ada.user["email_verified"] is False
    res = await finish(db_client)
    assert res.status_code == 200
    user = await me(db_client, res)
    assert user["id"] == ada.id and user["email_verified"] is True
    # The password still works too.
    login = await db_client.post("/v1/auth/login", json={"email": ada.email, "password": ada.password})
    assert login.status_code == 200
```

- `apps/backend/tests/integration/test_magic_link.py:13-31` — `test_sign_in_with_an_emailed_link` (signs in an unverified password account by link).

Conventions: layering is router → service → repository; a query other modules
need lives in the module's `repository.py`; services commit once per unit of
work; every action that matters is deliberate and documented in a docstring.
Never log tokens or passwords.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync` | exit 0 |
| Local services | `pnpm db:up` | Postgres running |
| Auth suites | `uv run pytest apps/backend/tests/integration/test_auth.py apps/backend/tests/integration/test_github_sign_in.py apps/backend/tests/integration/test_magic_link.py apps/backend/tests/integration/test_invites.py -q` | all pass |
| API token tests | `uv run pytest apps/backend/tests/integration -q -k "token"` | all pass |
| Whole backend | `uv run pytest apps/backend -q` | all pass |
| Lint | `uv run ruff check apps packages` | exit 0 |

## Scope

**In scope**:

- `apps/backend/src/dotrix_backend/modules/auth/service.py`
- `apps/backend/src/dotrix_backend/modules/api_tokens/repository.py` (add one method)
- `apps/backend/tests/integration/test_github_sign_in.py`
- `apps/backend/tests/integration/test_magic_link.py`
- `apps/backend/tests/integration/test_auth.py` (add one password-reset test)
- `CHANGELOG.md`

**Out of scope** (do NOT touch):

- The email-verification link itself (`ActionTokenPurpose.VERIFY_EMAIL`): a person who signed up with a password and clicks their own verification link must keep that password. Do not clear anything in that flow.
- `modules/invites/service.py` — accepting an invite needs an already signed-in session; by then the person came in through one of the flows fixed here.
- Requiring verification before a password account can be used at all (a larger product change).
- Local coding runners (`coding_runners`) registered by the account — noted under Maintenance.
- No schema change, no migration, no API shape change (so no `pnpm openapi`).

## Git workflow

- Branch from `stage`: `git fetch origin stage && git checkout -b advisor/005-unverified-account-claim origin/stage`. PRs go into `stage`, never `main`.
- Commit message: one short sentence-case line (e.g. `Claiming an unverified account clears the credentials set before it`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Confirm how a password-less account logs in

Read `AuthService.login` in `modules/auth/service.py` (starts at line 89).
Confirm that a user with `password_hash is None` is refused with the same
generic "wrong email or password" error as a wrong password, without raising an
unhandled exception.

**Verify**: `grep -n "password_hash" apps/backend/src/dotrix_backend/modules/auth/service.py` and read each hit. If `login` would crash on `None` (e.g. passes `None` into `verify_password` without a guard), that is a STOP condition — report it.

### Step 2: Add "revoke all API tokens for a user"

In `modules/api_tokens/repository.py`, add to `ApiTokenRepository`, following
the style of `RefreshTokenRepository.revoke_all_for_user`:

```python
    async def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        """Revoke every API token of a user (their CLI and scripts must sign in again)."""
        await self.session.execute(
            update(ApiToken).where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None)).values(revoked_at=now)
        )
```

Add the imports the file lacks (`update` from `sqlalchemy`, `datetime`).
Confirm the column is named `user_id` in `api_tokens/models.py`; if it has
another name, use that name.

**Verify**: `uv run ruff check apps/backend` → exit 0

### Step 3: Add the claim helper to `AuthService`

In `modules/auth/service.py`, in the helpers section (after
`# -- helpers ---`), add:

```python
    async def _claim_if_unverified(self, user: User, now: datetime) -> None:
        """An account whose address was never verified is being claimed by whoever just proved
        the inbox (GitHub's verified email, an emailed link). Whatever was set up before that
        may be someone else's: the password goes, and every session and API token is revoked.
        A verified account is left as it is."""
        if user.email_verified_at is not None:
            return
        user.password_hash = None
        await self.refresh_tokens.revoke_all_for_user(user.id, now)
        await ApiTokenRepository(self.session).revoke_all_for_user(user.id, now)
```

Import `ApiTokenRepository` from `dotrix_backend.modules.api_tokens.repository`.
If that import creates a circular import at startup (check with the Verify
command below), import it inside the method instead.

**Verify**: `uv run python -c "import dotrix_backend.main"` → exits 0 with no ImportError (it needs `DOTRIX_DATABASE_URL` and `DOTRIX_JWT_SECRET` in the environment or `.env`; if it fails only for missing settings, use `uv run pytest apps/backend/tests/unit/test_openapi.py -q` as the import check instead).

### Step 4: Call it in the three flows, before the address is marked verified and before new tokens are issued

1. `sign_in_with_magic_link`: replace
   `user.email_verified_at = user.email_verified_at or _now()` with:

```python
        now = _now()
        await self._claim_if_unverified(user, now)
        user.email_verified_at = user.email_verified_at or now
```

2. `sign_in_with_github`, in the not-yet-linked branch, immediately before the
   comment `# GitHub verified the address, which proves the inbox as a link would.`:

```python
            if user.email_verified_at is None:
                # Don't run for the account created just above (it is created verified).
                await self._claim_if_unverified(user, now)
```

   (The newly created user in the `if user is None:` branch is created with
   `email_verified_at=now`, so the helper is a no-op for it; the explicit `if`
   only documents that.)

3. `reset_password`: before `user.email_verified_at = user.email_verified_at or now`
   add `await self._claim_if_unverified(user, now)`. Order matters: the helper
   sets `password_hash = None`, so it must run **before** the line
   `user.password_hash = security.hash_password(data.new_password)` — move the
   helper call to directly after `now = _now()`.

In all three, the helper must run before `self._issue_tokens(user)`; otherwise
the session being created for the rightful owner would be revoked too.

**Verify**: `uv run ruff check apps/backend` → exit 0

### Step 5: Update and add tests

In `tests/integration/test_github_sign_in.py`, change
`test_links_an_existing_account_by_verified_email` so that its ending reads:

```python
    # The address was unverified until now: the password set before that is gone, and the
    # session that sign-up created is signed out.
    login = await db_client.post("/v1/auth/login", json={"email": ada.email, "password": ada.password})
    assert login.status_code == 401
    assert (await db_client.get("/v1/me", headers=ada.headers)).status_code == 401
```

Add `test_linking_a_verified_account_keeps_its_password`: sign up, verify the
email first (use the same approach existing tests use to verify an address —
search `tests/integration/test_auth.py` for `verify-email` and reuse its
helper/fixture, e.g. `email_token`), then `finish(db_client)`; assert the
password login still returns 200.

In `tests/integration/test_magic_link.py`, extend
`test_sign_in_with_an_emailed_link` (the account there is unverified): after
the magic-link sign-in succeeds, assert that logging in with `ada.password`
returns 401 and that `GET /v1/me` with the original `ada.headers` returns 401,
while `GET /v1/me` with the new `session` headers returns 200.

Add `test_claiming_an_unverified_account_revokes_its_api_tokens` (in
`test_magic_link.py`): sign up, create a personal API token with the sign-up
session (`POST /v1/me/tokens`; read an existing API-token test for the request
body — `grep -rn "/v1/me/tokens" apps/backend/tests/integration | head`),
then sign in by magic link; assert a request with `Authorization: Bearer <dtx token>`
now returns 401.

In `tests/integration/test_auth.py`, add
`test_resetting_an_unverified_accounts_password_revokes_its_api_tokens`,
modelled on the existing password-reset test in that file (search for
`reset`): same shape, plus the API-token assertion above.

**Verify**: `uv run pytest apps/backend/tests/integration/test_auth.py apps/backend/tests/integration/test_github_sign_in.py apps/backend/tests/integration/test_magic_link.py apps/backend/tests/integration/test_invites.py -q` → all pass

### Step 6: Whole backend, lint, changelog

Other tests may sign up with a password and then use a magic link or GitHub
while still holding the original session. Run everything:

**Verify**:
- `uv run pytest apps/backend -q` → all pass. If a test outside the in-scope files fails because it reuses a pre-verification session or password after a magic-link / GitHub sign-in, that is the intended new behaviour reaching a test that did not expect it: STOP and report the test names (do not edit out-of-scope tests).
- `uv run ruff check apps packages` → exit 0

Under `## [Unreleased]` → `### Security` in `CHANGELOG.md` add:
`- If an account's email was never verified, signing in to it with GitHub or an emailed link (or resetting its password) now removes the password set before that and signs out every browser, app and API token, so nobody who registered the address earlier keeps access. Verified accounts are unchanged.`

**Verify**: `python scripts/release.py check` → exit 0

## Test plan

- Changed: `test_links_an_existing_account_by_verified_email`, `test_sign_in_with_an_emailed_link`.
- New: verified-account-keeps-password (GitHub), API tokens revoked on claim (magic link), API tokens revoked on reset of an unverified account.
- Patterns: the existing tests in the same three files.

## Done criteria

- [ ] The four auth suites in Step 5 pass with the new tests present
- [ ] `uv run pytest apps/backend -q` exits 0
- [ ] `uv run ruff check apps packages` exits 0
- [ ] `grep -n "_claim_if_unverified" apps/backend/src/dotrix_backend/modules/auth/service.py` shows the definition and exactly three call sites
- [ ] `git diff --stat` shows no migration and no change under `packages/api-client`
- [ ] `git status --short` lists only in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The operator has not confirmed the product decision at the top of this plan.
- The excerpts in "Current state" do not match the live code.
- `login` cannot handle `password_hash is None` safely (Step 1).
- A test outside the in-scope files fails in Step 6.
- The web app's e2e tests are in your remit and `apps/web/e2e/auth.spec.ts` or `onboarding.spec.ts` relies on password login after a magic link for an unverified account — report it; the e2e files are out of scope.

## Maintenance notes

- User-visible effect to mention in release notes/support: someone who signed up with a password, never clicked the verification email, and then uses GitHub or a magic link will find their password no longer works; "Forgot password?" sets a new one.
- Not covered: the verification email itself. A person who clicks a verification link for a sign-up they did not make still confirms that account with the other party's password. Mitigating that needs a product change (e.g. no usable session before verification).
- Not covered: local coding runners registered by the earlier registrant (`coding_runners`). If runner credentials are separate from API tokens, add them to `_claim_if_unverified`.
- A reviewer should check ordering in all three flows: claim → mark verified → issue tokens.
