"""The background jobs, by name (see `core/jobs.py` for where they run)."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from .core.email import EmailMessage, EmailSendError
from .core.jobs import JobContext, JobFunction
from .modules.api_tokens.repository import DeviceAuthorizationRepository
from .modules.auth.repository import ActionTokenRepository, RefreshTokenRepository
from .modules.auth.service import AuthService
from .modules.documents.service import DocumentService
from .modules.invites.repository import InviteRepository

logger = logging.getLogger(__name__)

# How long finished rows are kept before cleanup deletes them.
TOKEN_RETENTION = timedelta(days=7)  # refresh tokens after expiry; email links after use or expiry; device logins
INVITE_RETENTION = timedelta(days=30)  # after expiry, revocation, or acceptance
CLEANUP_INTERVAL_SECONDS = 3600


async def send_email(ctx: JobContext, *, to: str, subject: str, body: str) -> None:
    try:
        await ctx.email.send(EmailMessage(to=to, subject=subject, body=body))
    except EmailSendError as exc:
        if exc.retryable:
            raise  # the worker tries again later
        # Retrying won't help (a rejected address, a bad key): record it and move on.
        logger.error("email not sent (%s): subject=%r: %s", exc.status, subject, exc.detail)


async def send_password_reset(ctx: JobContext, *, email: str) -> None:
    """The whole reset request runs here, not in the request: looking the account up and
    creating a token would otherwise make responses for real accounts measurably slower."""
    async with ctx.session_factory() as session:
        await AuthService(session, ctx.settings, ctx.email).send_password_reset(email)


async def cleanup_expired(ctx: JobContext, *, now: str | None = None) -> dict[str, int]:
    """Delete rows nothing will use again: expired refresh tokens, used or expired email-link
    tokens, finished device logins, and old invites. Runs hourly (the worker's cron, or a loop
    in the API process in local mode); safe to run any time, from any number of processes."""
    at = datetime.fromisoformat(now) if now else datetime.now(UTC)
    token_cutoff, invite_cutoff = at - TOKEN_RETENTION, at - INVITE_RETENTION
    async with ctx.session_factory() as session:
        deleted = {
            "refresh_tokens": await RefreshTokenRepository(session).delete_stale(token_cutoff),
            "action_tokens": await ActionTokenRepository(session).delete_stale(token_cutoff),
            "device_authorizations": await DeviceAuthorizationRepository(session).delete_stale(token_cutoff),
            "invites": await InviteRepository(session).delete_stale(invite_cutoff),
        }
        await session.commit()
    if any(deleted.values()):
        logger.info("cleanup deleted %s", ", ".join(f"{n} {name}" for name, n in deleted.items() if n))
    return deleted


async def convert_document(ctx: JobContext, *, document_id: str) -> None:
    """An uploaded document's markdown, made outside the request (big PDFs take a while)."""
    if ctx.storage is None:
        raise RuntimeError("File storage isn't configured")  # retried; the API refuses uploads anyway
    async with ctx.session_factory() as session:
        await DocumentService(session, ctx.storage).convert(uuid.UUID(document_id))


JOBS: dict[str, JobFunction] = {
    "send_email": send_email,
    "send_password_reset": send_password_reset,
    "cleanup_expired": cleanup_expired,
    "convert_document": convert_document,
}
