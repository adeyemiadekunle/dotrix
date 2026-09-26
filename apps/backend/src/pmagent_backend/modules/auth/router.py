"""Sign-up, login, tokens, email verification, password reset (FR-1)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, EmailDep, SessionDep, SettingsDep
from pmagent_backend.core.openapi import errors

from .schemas import (
    LoginRequest,
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

# TODO(rate-limit): throttle signup, login, and reset per IP and per email (needs Redis).
router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


def get_auth_service(session: SessionDep, settings: SettingsDep, email: EmailDep) -> AuthService:
    return AuthService(session, settings, email)


Auth = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/signup", status_code=status.HTTP_201_CREATED, responses=errors(409, 422))
async def signup(data: SignupRequest, auth: Auth) -> SignupResponse:
    """Create an account and sign in. Also creates your personal workspace and emails a
    verification link. Email is case-insensitive; passwords are 10–128 characters."""
    return await auth.signup(data)


@router.post("/login", responses=errors(401, 422))
async def login(data: LoginRequest, auth: Auth) -> TokenPair:
    """Exchange email and password for an access token (15 min) and a refresh token.
    A wrong password and an unknown email give the same 401."""
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


@router.post("/verify-email/resend", status_code=status.HTTP_202_ACCEPTED, responses=errors(401))
async def resend_verification(user: CurrentUser, auth: Auth) -> None:
    """Email a new verification link. Earlier links stop working."""
    await auth.resend_verification(user)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED, responses=errors(422))
async def request_password_reset(data: PasswordResetRequest, auth: Auth) -> None:
    """Email a password-reset link. Always 202, whether or not the account exists."""
    await auth.request_password_reset(data.email)


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
