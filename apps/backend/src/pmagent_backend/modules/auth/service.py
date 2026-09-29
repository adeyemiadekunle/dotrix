from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from pmagent_backend.core import email_templates, security
from pmagent_backend.core.email import EmailSender
from pmagent_backend.core.errors import Conflict, InvalidLink, Unauthorized
from pmagent_backend.core.jobs import Jobs
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.workspaces.service import WorkspaceService

from .github import GitHubProfile
from .models import ActionToken, ActionTokenPurpose, EmailSignup, OAuthAccount, RefreshToken, User
from .repository import (
    ActionTokenRepository,
    EmailSignupRepository,
    OAuthAccountRepository,
    RefreshTokenRepository,
    UserRepository,
)
from .schemas import (
    LoginRequest,
    PasswordResetConfirm,
    SignupRequest,
    SignupResponse,
    TokenPair,
    UserRead,
)


def _now() -> datetime:
    return datetime.now(UTC)


class AuthService:
    def __init__(
        self, session: AsyncSession, settings: Settings, email: EmailSender, jobs: Jobs | None = None
    ) -> None:
        self.session = session
        self.settings = settings
        self.email = email
        self.jobs = jobs  # the API's; None inside a job
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self.action_tokens = ActionTokenRepository(session)
        self.signups = EmailSignupRepository(session)
        self.oauth_accounts = OAuthAccountRepository(session)

    # -- sign-up and login -------------------------------------------------------

    async def signup(self, data: SignupRequest) -> SignupResponse:
        if await self.users.get_by_email(data.email):
            raise Conflict("An account with this email already exists")
        user = User(
            email=data.email,
            display_name=data.display_name,
            password_hash=security.hash_password(data.password),
        )
        self.users.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # concurrent sign-up with the same email
            raise Conflict("An account with this email already exists") from exc
        await WorkspaceService(self.session).create_personal(user)
        verify_token = await self._new_action_token(user, ActionTokenPurpose.VERIFY_EMAIL)
        tokens = self._issue_tokens(user)
        await self.session.commit()
        await self._send_verification(user, verify_token)
        return SignupResponse(user=UserRead.model_validate(user), tokens=tokens)

    async def login(self, data: LoginRequest) -> TokenPair:
        user = await self.users.get_by_email(data.email)
        # Always verify (against a dummy hash if needed) so timing doesn't reveal accounts.
        valid = security.verify_password(user.password_hash if user else None, data.password)
        if not user or not valid or not user.is_active:
            raise Unauthorized("Invalid email or password")
        if user.password_hash and security.password_needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(data.password)
        tokens = self._issue_tokens(user)
        await self.session.commit()
        return tokens

    async def refresh(self, refresh_token: str) -> TokenPair:
        now = _now()
        row = await self.refresh_tokens.get_by_hash_for_update(security.hash_token(refresh_token))
        if row is None:
            raise Unauthorized("Invalid refresh token")
        if row.revoked_at is not None:
            # A rotated-out token came back: treat the whole session as compromised.
            await self.refresh_tokens.revoke_family(row.family_id, now)
            await self.session.commit()
            raise Unauthorized("Refresh token reuse detected; please sign in again")
        if row.expires_at <= now:
            raise Unauthorized("Refresh token expired")
        user = await self.users.get(row.user_id)
        if user is None or not user.is_active:
            raise Unauthorized("Invalid refresh token")
        row.revoked_at = now
        tokens = self._issue_tokens(user, family_id=row.family_id)
        await self.session.commit()
        return tokens

    async def logout(self, refresh_token: str) -> None:
        row = await self.refresh_tokens.get_by_hash_for_update(security.hash_token(refresh_token))
        if row is not None:
            await self.refresh_tokens.revoke_family(row.family_id, _now())
            await self.session.commit()

    async def get_active_user(self, user_id: uuid.UUID) -> User:
        user = await self.users.get(user_id)
        if user is None or not user.is_active:
            raise Unauthorized("Invalid or expired access token")
        return user

    # -- email verification --------------------------------------------------------

    async def resend_verification(self, user: User) -> None:
        if user.email_verified:
            return
        token = await self._new_action_token(user, ActionTokenPurpose.VERIFY_EMAIL)
        await self.session.commit()
        await self._send_verification(user, token)

    async def verify_email(self, token: str) -> None:
        action = await self._consume(token, ActionTokenPurpose.VERIFY_EMAIL)
        user = await self.users.get(action.user_id)
        if user is not None and user.email_verified_at is None:
            user.email_verified_at = _now()
        await self.session.commit()

    # -- password reset ----------------------------------------------------------

    async def request_password_reset(self, email: str) -> None:
        """Always succeeds from the caller's view, so it can't be used to find accounts: the
        lookup and the email happen in a background job (`send_password_reset`)."""
        assert self.jobs is not None
        await self.jobs.enqueue("send_password_reset", email=email)

    async def send_password_reset(self, email: str) -> None:
        user = await self.users.get_by_email(email)
        if user is None or not user.is_active:
            return
        token = await self._new_action_token(user, ActionTokenPurpose.RESET_PASSWORD)
        await self.session.commit()
        link = self._link("/reset-password", token)
        await self.email.send(email_templates.reset_password(user.email, link, self.settings.password_reset_ttl_minutes))

    # -- magic-link sign-in ------------------------------------------------------

    async def request_magic_link(self, email: str) -> None:
        """Always succeeds from the caller's view, so it can't be used to find accounts: the
        lookup and the email happen in a background job (`send_magic_link`)."""
        assert self.jobs is not None
        await self.jobs.enqueue("send_magic_link", email=email)

    async def send_magic_link(self, email: str) -> None:
        """A sign-in link for an account; for an address without one, a link to create it."""
        ttl = self.settings.magic_link_ttl_minutes
        user = await self.users.get_by_email(email)
        if user is None:
            token = await self._new_signup_token(email)
            await self.session.commit()
            await self.email.send(email_templates.finish_signup(email, self._link("/signup/finish", token), ttl))
            return
        if not user.is_active:
            return
        token = await self._new_action_token(user, ActionTokenPurpose.MAGIC_LINK)
        await self.session.commit()
        await self.email.send(email_templates.magic_link(user.email, self._link("/magic-link", token), ttl))

    async def email_signup_address(self, token: str) -> str:
        """The address a sign-up link is for (without using the link up)."""
        signup = await self.signups.get_by_hash(security.hash_token(token))
        if signup is None or signup.used_at is not None or signup.expires_at <= _now():
            raise InvalidLink()
        return signup.email

    async def finish_email_signup(self, token: str, display_name: str) -> SignupResponse:
        """Create the account a sign-up link is for: verified (the link proved the inbox), no
        password (sign in by link, or set one with "Forgot password?"), a personal workspace."""
        now = _now()
        signup = await self.signups.get_by_hash_for_update(security.hash_token(token))
        if signup is None or signup.used_at is not None or signup.expires_at <= now:
            raise InvalidLink()
        signup.used_at = now
        if await self.users.get_by_email(signup.email):
            await self.session.commit()  # the link is used up either way
            raise Conflict("An account with this email already exists; sign in instead")
        user = User(email=signup.email, display_name=display_name, password_hash=None, email_verified_at=now)
        self.users.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # a sign-up with the same email at the same moment
            raise Conflict("An account with this email already exists; sign in instead") from exc
        await WorkspaceService(self.session).create_personal(user)
        tokens = self._issue_tokens(user)
        await self.session.commit()
        return SignupResponse(user=UserRead.model_validate(user), tokens=tokens)

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

    # -- sign in with GitHub ------------------------------------------------------

    async def sign_in_with_github(self, profile: GitHubProfile) -> TokenPair:
        """Sign in the account linked to this GitHub account. The first time, link it to the
        account with the same email (only an address GitHub has verified), or create one:
        verified, no password, with a personal workspace."""
        now = _now()
        linked = await self.oauth_accounts.get("github", profile.id)
        if linked is not None:
            user = await self.users.get(linked.user_id)
            if user is None or not user.is_active:
                raise Unauthorized("This account can't sign in")
            linked.login = profile.login
        else:
            if profile.verified_email is None:
                raise Unauthorized(
                    "Your GitHub account has no verified email address. Verify one on GitHub, "
                    "or sign up with your email instead."
                )
            user = await self.users.get_by_email(profile.verified_email)
            if user is None:
                name = (profile.name or profile.login).strip()[:100] or profile.login
                user = User(email=profile.verified_email, display_name=name, password_hash=None, email_verified_at=now)
                self.users.add(user)
                try:
                    await self.session.flush()
                except IntegrityError as exc:  # a sign-up with the same email at the same moment
                    raise Conflict("An account with this email was just created; try again") from exc
                await WorkspaceService(self.session).create_personal(user)
            elif not user.is_active:
                raise Unauthorized("This account can't sign in")
            # GitHub verified the address, which proves the inbox as a link would.
            user.email_verified_at = user.email_verified_at or now
            self.oauth_accounts.add(
                OAuthAccount(
                    user_id=user.id, provider="github", provider_user_id=profile.id, login=profile.login, created_at=now
                )
            )
            try:
                await self.session.flush()
            except IntegrityError as exc:  # the same GitHub account signing in twice at once
                raise Conflict("This GitHub account was just linked; try again") from exc
        tokens = self._issue_tokens(user)
        await self.session.commit()
        return tokens

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

    # -- helpers -----------------------------------------------------------------

    def _issue_tokens(self, user: User, family_id: uuid.UUID | None = None) -> TokenPair:
        now = _now()
        access_ttl = timedelta(minutes=self.settings.access_token_ttl_minutes)
        refresh = security.generate_token()
        self.refresh_tokens.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id or uuid7(),
                token_hash=security.hash_token(refresh),
                created_at=now,
                expires_at=now + timedelta(days=self.settings.refresh_token_ttl_days),
            )
        )
        access = security.create_access_token(
            user.id,
            secret=self.settings.jwt_secret.get_secret_value(),
            issuer=self.settings.jwt_issuer,
            ttl=access_ttl,
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(access_ttl.total_seconds()),
        )

    async def _new_action_token(self, user: User, purpose: ActionTokenPurpose) -> str:
        """Creates a token and invalidates older ones for the same purpose; caller commits."""
        now = _now()
        ttl = {
            ActionTokenPurpose.VERIFY_EMAIL: timedelta(hours=self.settings.email_verification_ttl_hours),
            ActionTokenPurpose.RESET_PASSWORD: timedelta(minutes=self.settings.password_reset_ttl_minutes),
            ActionTokenPurpose.MAGIC_LINK: timedelta(minutes=self.settings.magic_link_ttl_minutes),
        }[purpose]
        token = security.generate_token()
        await self.action_tokens.invalidate(user.id, purpose, now)
        self.action_tokens.add(
            ActionToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=security.hash_token(token),
                created_at=now,
                expires_at=now + ttl,
            )
        )
        return token

    async def _new_signup_token(self, email: str) -> str:
        """A sign-up link for an address with no account; older ones stop working. Caller commits."""
        now = _now()
        token = security.generate_token()
        await self.signups.invalidate(email, now)
        self.signups.add(
            EmailSignup(
                email=email,
                token_hash=security.hash_token(token),
                created_at=now,
                expires_at=now + timedelta(minutes=self.settings.magic_link_ttl_minutes),
            )
        )
        return token

    async def _consume(self, token: str, purpose: ActionTokenPurpose) -> ActionToken:
        now = _now()
        action = await self.action_tokens.get_by_hash_for_update(security.hash_token(token), purpose)
        if action is None or action.used_at is not None or action.expires_at <= now:
            raise InvalidLink()
        action.used_at = now
        return action

    async def _send_verification(self, user: User, token: str) -> None:
        await self.email.send(email_templates.verify_email(user.email, self._link("/verify-email", token)))

    def _link(self, path: str, token: str) -> str:
        return f"{self.settings.app_url.rstrip('/')}{path}?{urlencode({'token': token})}"
