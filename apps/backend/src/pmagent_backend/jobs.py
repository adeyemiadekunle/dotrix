"""The background jobs, by name (see `core/jobs.py` for where they run)."""
from __future__ import annotations

from .core.email import EmailMessage
from .core.jobs import JobContext, JobFunction
from .modules.auth.service import AuthService


async def send_email(ctx: JobContext, *, to: str, subject: str, body: str) -> None:
    await ctx.email.send(EmailMessage(to=to, subject=subject, body=body))


async def send_password_reset(ctx: JobContext, *, email: str) -> None:
    """The whole reset request runs here, not in the request: looking the account up and
    creating a token would otherwise make responses for real accounts measurably slower."""
    async with ctx.session_factory() as session:
        await AuthService(session, ctx.settings, ctx.email).send_password_reset(email)


JOBS: dict[str, JobFunction] = {
    "send_email": send_email,
    "send_password_reset": send_password_reset,
}
