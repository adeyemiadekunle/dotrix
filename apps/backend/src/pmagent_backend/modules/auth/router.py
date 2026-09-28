"""Sign-up, login, tokens, email verification, password reset (FR-1)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, EmailDep, JobsDep, SessionDep, SettingsDep
from pmagent_backend.core.openapi import errors

from .limits import LOGIN, MAGIC_LINK, PASSWORD_RESET, SIGNUP, VERIFY_RESEND, ThrottleDep
from .schemas import (
    LoginRequest,
    MagicLinkRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPair,
    TokenRequest,
    UserRead,
)
from .service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


def get_auth_service(session: SessionDep, settings: SettingsDep, email: EmailDep, jobs: JobsDep) -> AuthService:
    return AuthService(session, settings, email, jobs)


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
    """Email a sign-in link (valid 15 minutes, once). Always 202, whether or not the account
    exists (the lookup happens in the background). Rate-limited per IP and per email."""
    await throttle(MAGIC_LINK, data.email)
    await auth.request_magic_link(data.email)


@router.post("/magic-link/verify", responses=errors(400, 422))
async def sign_in_with_magic_link(data: TokenRequest, auth: Auth) -> TokenPair:
    """Exchange the token from a sign-in link for an access and refresh token, like login.
    The link works once, and following it also verifies the email address."""
    return await auth.sign_in_with_magic_link(data.token)


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
