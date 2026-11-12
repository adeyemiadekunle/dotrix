"""Admin console accounts from the server: `python -m dotrix_backend.admin_cli list | create | reset-password | reset-two-factor`.

Needs only DOTRIX_DATABASE_URL. The password is read from a prompt (twice) or from
DOTRIX_ADMIN_PASSWORD, never from the command line, so it stays out of the process list and
shell history."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.errors import DomainError
from dotrix_backend.core.settings import get_database_settings
from dotrix_backend.db.session import create_engine, create_sessionmaker
from dotrix_backend.modules.admin import accounts


def read_password() -> str:
    from_env = os.environ.get("DOTRIX_ADMIN_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Password again: "):
        raise DomainError("The passwords don't match")
    return first


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dotrix_backend.admin_cli", description="Manage admin console accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List admin accounts")
    create = commands.add_parser("create", help="Create an admin account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    reset = commands.add_parser("reset-password", help="Set a new password and sign the admin out everywhere")
    reset.add_argument("--email", required=True)
    reset_2fa = commands.add_parser(
        "reset-two-factor", help="Clear an admin's authenticator and recovery codes and sign them out; they set one up at the next sign-in"
    )
    reset_2fa.add_argument("--email", required=True)
    return parser


async def run(args: argparse.Namespace, password: Callable[[], str] = read_password) -> list[str]:
    engine = create_engine(get_database_settings().database_url)
    try:
        async with create_sessionmaker(engine)() as session:
            lines = await execute(session, args, password)
            await session.commit()
            return lines
    finally:
        await engine.dispose()


async def execute(session: AsyncSession, args: argparse.Namespace, password: Callable[[], str]) -> list[str]:
    handlers: dict[str, Callable[[], Awaitable[list[str]]]] = {
        "list": lambda: _list(session),
        "create": lambda: _create(session, args, password),
        "reset-password": lambda: _reset(session, args, password),
        "reset-two-factor": lambda: _reset_two_factor(session, args),
    }
    return await handlers[args.command]()


async def _list(session: AsyncSession) -> list[str]:
    return [f"{a.email}\t{a.name}\t{a.created_at.date().isoformat()}" for a in await accounts.list_admins(session)]


async def _create(session: AsyncSession, args: argparse.Namespace, password: Callable[[], str]) -> list[str]:
    admin = await accounts.create_admin(session, email=args.email, name=args.name, password=password(), actor_email="command line")
    return [f"Created admin {admin.email}"]


async def _reset(session: AsyncSession, args: argparse.Namespace, password: Callable[[], str]) -> list[str]:
    admin = await accounts.reset_admin_password(session, email=args.email, password=password())
    return [f"Password changed for {admin.email}; its sessions were signed out"]


async def _reset_two_factor(session: AsyncSession, args: argparse.Namespace) -> list[str]:
    admin = await accounts.reset_admin_two_factor(session, email=args.email)
    return [f"Two-factor cleared for {admin.email}; its sessions were signed out"]


def main() -> None:
    args = build_parser().parse_args()
    try:
        if sys.platform == "win32":
            lines = asyncio.run(run(args), loop_factory=asyncio.SelectorEventLoop)
        else:
            lines = asyncio.run(run(args))
    except DomainError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
