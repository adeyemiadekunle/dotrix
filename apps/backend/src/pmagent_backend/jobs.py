"""The background jobs, by name (see `core/jobs.py` for where they run)."""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from .core.email import EmailMessage, EmailSendError
from .core.jobs import JobContext, JobFunction
from .modules.agents.service import continue_due_runs
from .modules.api_tokens.repository import DeviceAuthorizationRepository
from .modules.auth.repository import (
    ActionTokenRepository,
    AuthSessionRepository,
    EmailSignupRepository,
    RefreshTokenRepository,
)
from .modules.auth.service import AuthService
from .modules.automations.service import AutomationService
from .modules.code.service import CodeService
from .modules.coding.models import CodingRun, CodingRunStatus
from .modules.documents.service import DocumentService
from .modules.invites.repository import InviteRepository
from .modules.notifications.emails import NotificationEmails
from .modules.projects.models import Project
from .modules.research.service import KEEP_PAGES_FOR, delete_stale_pages
from .modules.search.service import KnowledgeIndex

logger = logging.getLogger(__name__)

# How long finished rows are kept before cleanup deletes them.
TOKEN_RETENTION = timedelta(days=7)  # refresh tokens after expiry; email links after use or expiry; device logins
INVITE_RETENTION = timedelta(days=30)  # after expiry, revocation, or acceptance
CLEANUP_INTERVAL_SECONDS = 3600
INDEX_INTERVAL_SECONDS = 60
AUTOMATIONS_INTERVAL_SECONDS = 60
EMAIL_INTERVAL_SECONDS = 60


async def send_email(ctx: JobContext, *, to: str, subject: str, body: str, html: str | None = None) -> None:
    try:
        await ctx.email.send(EmailMessage(to=to, subject=subject, body=body, html=html))
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
    """Delete rows nothing will use again: expired refresh tokens and sessions, used or expired email-link
    tokens, finished device logins, old invites, web pages read over a month ago, and checkouts of repos
    no longer connected (on this machine). Runs hourly (the worker's cron, or a loop
    in the API process in local mode); safe to run any time, from any number of processes."""
    # Imported here: it imports the issues service, which needs every model loaded first.
    from .modules.coding.runner import end_cut_off_runs

    at = datetime.fromisoformat(now) if now else datetime.now(UTC)
    token_cutoff, invite_cutoff = at - TOKEN_RETENTION, at - INVITE_RETENTION
    async with ctx.session_factory() as session:
        deleted = {
            "refresh_tokens": await RefreshTokenRepository(session).delete_stale(token_cutoff),
            "auth_sessions": await AuthSessionRepository(session).delete_stale(
                token_cutoff, token_cutoff - timedelta(days=ctx.settings.refresh_token_ttl_days)
            ),
            "action_tokens": await ActionTokenRepository(session).delete_stale(token_cutoff),
            "email_signups": await EmailSignupRepository(session).delete_stale(token_cutoff),
            "device_authorizations": await DeviceAuthorizationRepository(session).delete_stale(token_cutoff),
            "invites": await InviteRepository(session).delete_stale(invite_cutoff),
            "web_pages": await delete_stale_pages(session, at - KEEP_PAGES_FOR),
            "cut_off_coding_runs": await end_cut_off_runs(session, ctx.settings),
        }
        await session.commit()
        if ctx.checkouts is not None:
            deleted["checkouts"] = await CodeService(session, ctx.checkouts).prune()
    if any(deleted.values()):
        logger.info("cleanup deleted %s", ", ".join(f"{n} {name}" for name, n in deleted.items() if n))
    return deleted


async def sync_repository(ctx: JobContext, *, project_id: str) -> None:
    """Check out a connected repo's default branch afresh for agents to read (after it's
    connected, and after each push). A failure is recorded on the repo, not retried: the next
    push or agent run tries again."""
    if ctx.checkouts is None:
        return
    async with ctx.session_factory() as session:
        await CodeService(session, ctx.checkouts).sync(uuid.UUID(project_id))


async def run_coding(ctx: JobContext, *, run_id: str) -> None:
    """An approved coding run: the agent in a sandbox, then the branch and the PR. Never retried
    (it may have pushed); it records its own failure."""
    if ctx.coding is None:
        async with ctx.session_factory() as session:
            run = await session.get(CodingRun, uuid.UUID(run_id))
            if run is not None and run.status is CodingRunStatus.QUEUED:
                run.status, run.error = CodingRunStatus.FAILED, "Coding runs aren't executed on this server"
                run.finished_at = datetime.now(UTC)
                await session.commit()
        return
    await ctx.coding.execute(uuid.UUID(run_id))


async def run_automations(ctx: JobContext) -> dict[str, int]:
    """Start the automations whose events happened or whose schedule came round. Every minute
    (the worker's cron, or a loop in the API in local mode)."""
    if ctx.runner is None:
        return {}
    async with ctx.session_factory() as session:
        done = await AutomationService(
            session, ctx.runner, workspace_daily_runs=ctx.settings.automation_daily_runs,
            workspace_daily_tokens=ctx.settings.automation_daily_tokens
        ).run_due()
        # Runs whose person asked to continue once their model's limit reset.
        done["continued"] = await continue_due_runs(session, ctx.runner)
    if done.get("fired") or done.get("skipped") or done.get("continued"):
        logger.info("automations: %s", done)
    return done


async def email_notifications(ctx: JobContext) -> dict[str, int]:
    """Email new notifications to people who want them as they happen, and the daily digests
    from 08:00 UTC. Every minute (the worker's cron, or a loop in the API in local mode)."""
    async with ctx.session_factory() as session:
        emails = NotificationEmails(session, ctx.email, ctx.settings.app_url)
        done = await emails.send_due()
        done["digests"] = await emails.send_digests()
    if done["emails"] or done["digests"]:
        logger.info("notification emails: %s", done)
    return done


async def convert_document(ctx: JobContext, *, document_id: str) -> None:
    """An uploaded document's markdown, made outside the request (big PDFs take a while)."""
    if ctx.storage is None:
        raise RuntimeError("File storage isn't configured")  # retried; the API refuses uploads anyway
    async with ctx.session_factory() as session:
        await DocumentService(session, ctx.storage).convert(uuid.UUID(document_id))


async def send_magic_link(ctx: JobContext, *, email: str) -> None:
    """Like password resets: the lookup happens here, so the response can't reveal accounts."""
    async with ctx.session_factory() as session:
        await AuthService(session, ctx.settings, ctx.email).send_magic_link(email)


async def index_knowledge(ctx: JobContext, *, project_id: str | None = None) -> int:
    """Bring the search index up to date: re-chunk changed documents and issues and embed what
    has no vector yet, for one project or every project that's behind. Runs every minute (the
    worker's cron, or a loop in the API in local mode); searches keep keyword results current
    themselves, so this mostly adds the vectors."""
    done = 0
    async with ctx.session_factory() as session:
        index = KnowledgeIndex(session, ctx.embedder)
        ids = [uuid.UUID(project_id)] if project_id else await index.stale_projects()
        for pid in ids:
            project = await session.get(Project, pid)
            if project is None:
                continue
            await index.sync(project)
            done += await index.embed_pending(project)
    return done


JOBS: dict[str, JobFunction] = {
    "send_email": send_email,
    "send_password_reset": send_password_reset,
    "send_magic_link": send_magic_link,
    "cleanup_expired": cleanup_expired,
    "convert_document": convert_document,
    "index_knowledge": index_knowledge,
    "sync_repository": sync_repository,
    "run_automations": run_automations,
    "run_coding": run_coding,
    "email_notifications": email_notifications,
}
