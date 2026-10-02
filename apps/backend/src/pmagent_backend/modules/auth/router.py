"""Sign-up, login, tokens, email verification, password reset (FR-1)."""
from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from pmagent_backend.api.deps import (
    CurrentUser,
    EmailDep,
    JobsDep,
    SessionDep,
    SessionUser,
    SettingsDep,
)
from pmagent_backend.core import security
from pmagent_backend.core.openapi import errors
from pmagent_backend.core.ratelimit import client_ip

from .github import GitHubDep
from .limits import LOGIN, MAGIC_LINK, PASSWORD_RESET, SIGNUP, VERIFY_RESEND, ThrottleDep
from .profile import MAX_AVATAR_BYTES, ProfileService
from .schemas import (
    AuthProviders,
    EmailSignupAddress,
    EmailSignupFinish,
    GitHubFinish,
    GitHubStart,
    LoginRequest,
    MagicLinkRequest,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    ProfileUpdate,
    RefreshRequest,
    SessionRead,
    SignedOut,
    SignInMethods,
    SignupRequest,
    SignupResponse,
    TokenPair,
    TokenRequest,
    UserRead,
)
from .service import AuthService
from .sessions import ClientInfo, SessionService

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


def get_auth_service(
    request: Request, session: SessionDep, settings: SettingsDep, email: EmailDep, jobs: JobsDep
) -> AuthService:
    auth = AuthService(session, settings, email, jobs)
    # The web app passes on the browser's User-Agent and address (see apps/web lib/session.ts).
    auth.client = ClientInfo(
        user_agent=request.headers.get("user-agent", "")[:500], ip=client_ip(request, settings.trusted_proxies)
    )
    return auth


Auth = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/signup", status_code=status.HTTP_201_CREATED, responses=errors(409, 422, 429))
async def signup(data: SignupRequest, auth: Auth, throttle: ThrottleDep) -> SignupResponse:
    """Create an account and sign in. Also creates your personal workspace and emails a
    verification link. Email is case-insensitive; passwords are 10–128 characters.
    Rate-limited per IP and per email."""
    await throttle(SIGNUP, data.email)
    return await auth.signup(data)


@router.post("/login", responses=errors(401, 422, 429))
async def login(data: LoginRequest, auth: Auth, throttle: ThrottleDep) -> TokenPair:
    """Exchange email and password for an access token (15 min) and a refresh token.
    A wrong password and an unknown email give the same 401. Rate-limited per IP and per
    email (10 attempts in 15 minutes)."""
    await throttle(LOGIN, data.email)
    return await auth.login(data)


@router.post("/refresh", responses=errors(401, 422))
async def refresh(data: RefreshRequest, auth: Auth) -> TokenPair:
    """Get a new token pair. The refresh token you send is used up; store the new one.
    Reusing an old refresh token signs that session out everywhere."""
    return await auth.refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, responses=errors(422))
async def logout(data: RefreshRequest, auth: Auth) -> None:
    """End this session: revokes the refresh token and every token rotated from it."""
    await auth.logout(data.refresh_token)


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT, responses=errors(400, 422))
async def verify_email(data: TokenRequest, auth: Auth) -> None:
    """Confirm an email address with the token from the verification link."""
    await auth.verify_email(data.token)


@router.post("/verify-email/resend", status_code=status.HTTP_202_ACCEPTED, responses=errors(401, 429))
async def resend_verification(user: CurrentUser, auth: Auth, throttle: ThrottleDep) -> None:
    """Email a new verification link. Earlier links stop working. Rate-limited."""
    await throttle(VERIFY_RESEND, user.email)
    await auth.resend_verification(user)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED, responses=errors(422, 429))
async def request_password_reset(data: PasswordResetRequest, auth: Auth, throttle: ThrottleDep) -> None:
    """Email a password-reset link. Always 202, whether or not the account exists (the
    lookup happens in the background). Rate-limited per IP and per email."""
    await throttle(PASSWORD_RESET, data.email)
    await auth.request_password_reset(data.email)


@router.post("/magic-link/request", status_code=status.HTTP_202_ACCEPTED, responses=errors(422, 429))
async def request_magic_link(data: MagicLinkRequest, auth: Auth, throttle: ThrottleDep) -> None:
    """Email a link (valid 15 minutes, once): a sign-in link for an account or, for an
    address without one, a link to create it (`/v1/auth/magic-link/signup`). Always 202 (the
    lookup happens in the background). Rate-limited per IP and per email."""
    await throttle(MAGIC_LINK, data.email)
    await auth.request_magic_link(data.email)


@router.post("/magic-link/verify", responses=errors(400, 422))
async def sign_in_with_magic_link(data: TokenRequest, auth: Auth) -> TokenPair:
    """Exchange the token from a sign-in link for an access and refresh token, like login.
    The link works once, and following it also verifies the email address."""
    return await auth.sign_in_with_magic_link(data.token)


@router.post("/magic-link/signup/lookup", responses=errors(400, 422))
async def email_signup_address(data: TokenRequest, auth: Auth) -> EmailSignupAddress:
    """The address a sign-up link is for, to show while asking for a name. Doesn't use the link up."""
    return EmailSignupAddress(email=await auth.email_signup_address(data.token))


@router.post("/magic-link/signup", status_code=status.HTTP_201_CREATED, responses=errors(400, 409, 422, 429))
async def finish_email_signup(data: EmailSignupFinish, auth: Auth, throttle: ThrottleDep) -> SignupResponse:
    """Create an account from a sign-up link and sign in. The email is verified (the link
    proved the inbox) and there's no password (sign in by link, or set one with a password
    reset). Also creates the personal workspace. 409 if the address got an account meanwhile."""
    email = await auth.email_signup_address(data.token)
    await throttle(SIGNUP, email)
    return await auth.finish_email_signup(data.token, data.display_name)


@router.get("/providers")
async def auth_providers(github: GitHubDep) -> AuthProviders:
    """Which other ways to sign in are set up, so sign-in pages offer only those."""
    return AuthProviders(github=github.configured)


@router.post("/oauth/github/start", responses=errors(503))
async def start_github_sign_in(github: GitHubDep) -> GitHubStart:
    """Begin signing in with GitHub: where to send the person, and the `state` to keep and
    compare with the one GitHub sends back (so nobody can sign you in to their account).
    503 when GitHub sign-in isn't set up."""
    state = security.generate_token()
    return GitHubStart(authorize_url=github.authorize_url(state), state=state)


@router.post("/oauth/github/finish", responses=errors(401, 409, 422, 503))
async def finish_github_sign_in(data: GitHubFinish, auth: Auth, github: GitHubDep) -> TokenPair:
    """Exchange the `code` GitHub sent back for an access and refresh token, like login. The
    first time, links the GitHub account to the account with the same email (only one GitHub
    has verified) or creates one, with a personal workspace. Check `state` before calling."""
    return await auth.sign_in_with_github(await github.profile(data.code))


@router.get("/oauth/github/callback", include_in_schema=False)
async def github_callback(request: Request, settings: SettingsDep) -> RedirectResponse:
    """For a GitHub app registered with this API as its callback URL: forward to the web
    app's callback, which checks the state and finishes the sign-in."""
    params = {k: v for k, v in request.query_params.items() if k in ("code", "state", "error")}
    target = f"{settings.app_url.rstrip('/')}/api/auth/github/callback"
    return RedirectResponse(f"{target}?{urlencode(params)}", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT, responses=errors(400, 422)
)
async def confirm_password_reset(data: PasswordResetConfirm, auth: Auth) -> None:
    """Set a new password with the token from the reset link. Signs out every session."""
    await auth.reset_password(data)


@me_router.get("/me", responses=errors(401))
async def me(user: CurrentUser) -> UserRead:
    """The signed-in user."""
    return UserRead.model_validate(user)


def get_session_service(session: SessionDep, settings: SettingsDep) -> SessionService:
    return SessionService(session, settings)


Sessions = Annotated[SessionService, Depends(get_session_service)]


def _current_session(request: Request) -> uuid.UUID | None:
    return getattr(request.state, "session_id", None)


@me_router.get("/me/sessions", responses=errors(401))
async def list_sessions(request: Request, user: CurrentUser, sessions: Sessions) -> list[SessionRead]:
    """The browsers and desktop apps you're signed in on, the one you're using first (`current`).
    The CLI and tools are your API tokens (`GET /v1/me/tokens`)."""
    return await sessions.list(user, _current_session(request))


@me_router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(401, 403, 404))
async def sign_out_session(session_id: uuid.UUID, user: SessionUser, sessions: Sessions) -> None:
    """Sign a browser or the desktop app out: it can't refresh, and its access stops at once.
    Signing out the one you're using signs you out here too. Not with an API token."""
    await sessions.sign_out(user, session_id)


@me_router.post("/me/sessions/sign-out-others", responses=errors(401, 403))
async def sign_out_other_sessions(request: Request, user: SessionUser, sessions: Sessions) -> SignedOut:
    """Sign out every browser and desktop app but the one you're using. Not with an API token."""
    return SignedOut(signed_out=await sessions.sign_out_others(user, _current_session(request)))


def get_profile_service(session: SessionDep) -> ProfileService:
    return ProfileService(session)


Profile = Annotated[ProfileService, Depends(get_profile_service)]

# Photo responses: the address carries the photo's version (`?v=`), so browsers may keep it.
IMAGE_RESPONSE = {200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}, "description": "The photo"}}


def image(content_type: str, content: bytes) -> Response:
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )


@me_router.patch("/me", responses=errors(401, 422))
async def update_profile(data: ProfileUpdate, user: CurrentUser, profile: Profile) -> UserRead:
    """Change your name or what you do (shown next to your name to your team)."""
    return await profile.update(user, data)


@me_router.get("/me/sign-in-methods", responses=errors(401))
async def sign_in_methods(user: CurrentUser, profile: Profile) -> SignInMethods:
    """How you can sign in: a password, an email link (always), and linked accounts (GitHub)."""
    return await profile.sign_in_methods(user)


@me_router.put("/me/sign-in-methods/github", responses=errors(401, 403, 409, 422, 503))
async def link_github(data: GitHubFinish, user: SessionUser, profile: Profile, github: GitHubDep) -> SignInMethods:
    """Link a GitHub account to yours, so you can sign in with it: the `code` GitHub sent back
    after a sign-in started in link mode (check `state` first). 409 if it signs in to another
    account, or you've linked a different one. Not with an API token."""
    return await profile.link_github(user, await github.profile(data.code))


@me_router.put("/me/password", responses=errors(401, 403, 422, 429))
async def change_password(
    data: PasswordChange, request: Request, user: SessionUser, profile: Profile, throttle: ThrottleDep
) -> SignedOut:
    """Change your password, or set one if you sign in only with GitHub or email links. The
    current password is required when you have one (422 `wrong_password`). Signs out your other
    browsers and apps (`signed_out`). Rate-limited like sign-in. Not with an API token."""
    await throttle(LOGIN, user.email)
    return SignedOut(signed_out=await profile.change_password(user, data, _current_session(request)))


@me_router.delete(
    "/me/sign-in-methods/{provider}", status_code=status.HTTP_204_NO_CONTENT, responses=errors(401, 404, 409)
)
async def unlink_sign_in_method(provider: str, user: CurrentUser, profile: Profile) -> None:
    """Stop signing in with a linked account. 409 while it's your only way in besides an email
    link: set a password first (Forgot password)."""
    await profile.unlink(user, provider)


@me_router.put("/me/avatar", responses=errors(401, 422))
async def set_avatar(
    user: CurrentUser,
    profile: Profile,
    file: Annotated[UploadFile, File(description="PNG, JPEG, or WebP, at most 500 KB (256 px square is plenty)")],
) -> UserRead:
    """Set your profile photo, replacing any earlier one."""
    content = await file.read(MAX_AVATAR_BYTES + 1)
    return await profile.set_avatar(user, file.content_type or "", content)


@me_router.delete("/me/avatar", responses=errors(401))
async def remove_avatar(user: CurrentUser, profile: Profile) -> UserRead:
    """Remove your profile photo (your initials show instead)."""
    return await profile.remove_avatar(user)


@me_router.get("/me/avatar", response_class=Response, responses=IMAGE_RESPONSE | errors(401, 404))
async def get_avatar(user: CurrentUser, profile: Profile) -> Response:
    """Your profile photo. 404 without one."""
    avatar = await profile.avatar(user.id)
    return image(avatar.content_type, avatar.content)
