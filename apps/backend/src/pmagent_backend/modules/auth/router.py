"""Sign-up, login, tokens, email verification, password reset (FR-1)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from pmagent_backend.api.deps import CurrentUser, EmailDep, SessionDep, SettingsDep

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


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(data: SignupRequest, auth: Auth) -> SignupResponse:
    return await auth.signup(data)


@router.post("/login")
async def login(data: LoginRequest, auth: Auth) -> TokenPair:
    return await auth.login(data)


@router.post("/refresh")
async def refresh(data: RefreshRequest, auth: Auth) -> TokenPair:
    return await auth.refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, auth: Auth) -> None:
    await auth.logout(data.refresh_token)


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(data: TokenRequest, auth: Auth) -> None:
    await auth.verify_email(data.token)


@router.post("/verify-email/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(user: CurrentUser, auth: Auth) -> None:
    await auth.resend_verification(user)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(data: PasswordResetRequest, auth: Auth) -> None:
    await auth.request_password_reset(data.email)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(data: PasswordResetConfirm, auth: Auth) -> None:
    await auth.reset_password(data)


@me_router.get("/me")
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
