"""Host secrets: a project's credentials for hosts in its network policy, added outside Kai's sandbox.

A host secret is a value (an npm token, a private registry's password, a test API's key) for one host the project's
network policy allows (network.py). The sandbox never holds it: Kai's commands see a placeholder in the environment
variable the secret is named after, send it as they would the real value (`Authorization: Bearer $NPM_TOKEN`), and
the sandbox's proxy puts the real value into that header on requests to that host only:

- Docker Cloud (staging and production): a custom Docker secret per host secret, injected into the host's requests
  (`docker_cloud.py`), as the model key is.
- OpenShell (development): a provider per host secret, from a profile made for the turn (`sandbox.py`), as the model
  key is; the host then goes through OpenShell's inspecting proxy instead of the policy's relayed endpoints.
- The local sandbox and people's own computers never get them (a local turn has no proxy to keep them out).

Values are write-only: stored encrypted (`core/crypto.Secrets`), never returned, logged or put in a brief, and every
change is audited by name and host, never value. A coding session pins its project's secrets (names, hosts, headers;
`coding_runs.secret_snapshot`) with its first turn, as it pins its network policy; each turn reads the values as they
are then, so a rotated token reaches running sessions, and a secret goes only if its host is still the pinned one
and still allowed by the turn's network policy. A secret deleted or moved since is left out, and the turn says so.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.errors import Conflict, NotFound
from dotrix_backend.modules.audit.models import AuthorType
from dotrix_backend.modules.audit.service import AuditLog
from dotrix_backend.modules.projects.models import Project
from dotrix_backend.modules.workspaces.models import Membership, Workspace
from dotrix_engine import network_policy
from dotrix_engine.network_policy import InvalidEntry

from .environments import _NAME, RESERVED, RESERVED_PREFIXES
from .models import CodingSecret

MAX_SECRETS = 20
MAX_VALUE = 8192
_HEADER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
# Headers a proxy must not be asked to write: they'd change where or how the request goes.
_FORBIDDEN_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer",
                                "proxy-authorization", "proxy-connection", "keep-alive", "cookie", "set-cookie"})


def check_name(name: str) -> None:
    """A secret's name is the environment variable Kai's commands read its placeholder from."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"{name!r} isn't a variable name (letters, digits and _, not starting with a digit)")
    upper = name.upper()
    if upper in RESERVED or upper.startswith(RESERVED_PREFIXES):
        raise ValueError(f"{name} is set by the sandbox or the coding tool; choose another name")


def check_host(raw: str) -> str:
    """One exact host (`host` or `host:port`) as the network policy stores it: a secret goes to one host only."""
    try:
        entry = network_policy.parse_entry(raw)
    except InvalidEntry as exc:
        raise ValueError(str(exc)) from exc
    if entry.subdomains:
        raise ValueError("A secret goes to one host: name it exactly (api.example.com), not *.example.com")
    return str(entry)


class CodingSecretSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = Field(description="The one host (`api.example.com` or `host:port`) the value is sent to; it must be "
                                  "in the project's network policy")
    header: str = Field(default="Authorization", description="The request header the value goes in")
    prefix: str = Field(default="Bearer ", max_length=32, description=(
        "What comes before the value in the header (`Bearer `, `Token `, or nothing)"))
    value: str | None = Field(default=None, description=(
        "The secret. Required for a new secret; leave it out to keep the stored one while changing the rest. Never "
        "returned"))

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        return check_host(value)

    @field_validator("header")
    @classmethod
    def _header(cls, value: str) -> str:
        if not _HEADER.fullmatch(value) or value.lower() in _FORBIDDEN_HEADERS:
            raise ValueError(f"{value!r} can't carry a secret; use Authorization or the header the service documents")
        return value

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("The prefix must be printable text such as `Bearer `")
        return value

    @field_validator("value")
    @classmethod
    def _value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or len(value) > MAX_VALUE or any(c in value for c in "\x00\r\n"):
            raise ValueError(f"The value must be one line of 1 to {MAX_VALUE} characters")
        return value


class CodingSecretRead(BaseModel):
    """A host secret without its value."""

    name: str
    host: str
    header: str
    prefix: str
    version: int
    allowed: bool = Field(description="Whether the project's network policy allows its host now; a secret whose "
                                      "host isn't allowed isn't sent")
    updated_at: datetime
    updated_by_id: uuid.UUID | None


@dataclass(frozen=True)
class HostSecret:
    """What a sandbox needs to add one secret to its host's requests. `value` never leaves the worker except to the
    sandbox provider's secret store (Docker's, OpenShell's gateway)."""

    name: str
    host: str  # exact host name
    port: int
    header: str
    prefix: str
    value: str
    version: int

    def __repr__(self) -> str:  # never the value
        return f"HostSecret({self.name}, {self.host}:{self.port})"

    @property
    def entry(self) -> str:
        return self.host if self.port == network_policy.DEFAULT_PORT else f"{self.host}:{self.port}"

    @property
    def placeholder(self) -> str:
        """OpenShell's placeholder; Docker Cloud gives its own when the secret is stored."""
        return f"openshell:resolve:env:{self.name}"


def _read(row: CodingSecret, allow: list[str]) -> CodingSecretRead:
    entry = network_policy.parse_entry(row.host)
    return CodingSecretRead(
        name=row.name, host=row.host, header=row.header, prefix=row.prefix, version=row.version,
        allowed=network_policy.permits(network_policy.parse(allow, limit=None), entry.host, entry.port),
        updated_at=row.updated_at, updated_by_id=row.updated_by_id)


async def _rows(session: AsyncSession, project: Project) -> list[CodingSecret]:
    return list((await session.scalars(select(CodingSecret).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id,
    ).order_by(CodingSecret.name))).all())


async def secret_names(session: AsyncSession, project: Project) -> set[str]:
    return set((await session.scalars(select(CodingSecret.name).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id))).all())


async def _allowed(session: AsyncSession, project: Project) -> list[str]:
    from .network import allowed_hosts

    await session.refresh(project, ["sandbox_network"])
    return allowed_hosts(await session.get(Workspace, project.workspace_id), project)


async def list_secrets(session: AsyncSession, project: Project) -> list[CodingSecretRead]:
    allow = await _allowed(session, project)
    return [_read(row, allow) for row in await _rows(session, project)]


async def save_secret(
    session: AsyncSession, cipher: Secrets, member: Membership, project: Project, name: str, data: CodingSecretSave,
) -> CodingSecretRead:
    """Add or change a host secret. 409 when its host isn't in the project's network policy, its name is one of the
    environment's variables, or the project has its maximum; a new secret needs a value."""
    from .environments import profile

    try:
        check_name(name)
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    allow = await _allowed(session, project)
    entry = network_policy.parse_entry(data.host)
    if not network_policy.permits(network_policy.parse(allow, limit=None), entry.host, entry.port):
        raise Conflict(f"{data.host} isn't in this project's network policy: allow it in Network access first")
    if name in profile(project.coding_environment).variables:
        raise Conflict(f"{name} is one of the environment's variables; remove it there or choose another name")
    row = await session.scalar(select(CodingSecret).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id,
        CodingSecret.name == name).with_for_update())
    now = datetime.now(UTC)
    created = row is None
    if row is None:
        if data.value is None:
            raise Conflict("A new secret needs its value")
        if len(await secret_names(session, project)) >= MAX_SECRETS:
            raise Conflict(f"A project has at most {MAX_SECRETS} secrets")
        row = CodingSecret(workspace_id=project.workspace_id, project_id=project.id, name=name, version=1,
                           created_at=now, encrypted="")
        session.add(row)
    else:
        row.version += 1
    row.host, row.header, row.prefix = data.host, data.header, data.prefix
    if data.value is not None:
        row.encrypted = cipher.encrypt(data.value)
    row.updated_by_id, row.updated_at = member.user_id, now
    await session.flush()
    AuditLog(session).record(
        workspace_id=project.workspace_id, project_id=project.id,
        action="coding_secret.created" if created else "coding_secret.updated", target=name,
        actor_type=AuthorType.USER, actor_user_id=member.user_id,
        details={"name": name, "host": row.host, "header": row.header, "version": row.version,
                 "value_changed": data.value is not None})
    await session.commit()
    return _read(row, allow)


async def delete_secret(session: AsyncSession, member: Membership, project: Project, name: str) -> None:
    row = await session.scalar(select(CodingSecret).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id,
        CodingSecret.name == name))
    if row is None:
        raise NotFound("No such secret")
    await session.delete(row)
    AuditLog(session).record(
        workspace_id=project.workspace_id, project_id=project.id, action="coding_secret.deleted", target=name,
        actor_type=AuthorType.USER, actor_user_id=member.user_id, details={"name": name, "host": row.host})
    await session.commit()


# -- pinned per session, loaded per turn -------------------------------------------------------------------------


def _pin(row: CodingSecret) -> dict[str, Any]:
    return {"name": row.name, "host": row.host, "header": row.header, "prefix": row.prefix}


async def project_snapshot(session: AsyncSession, project: Project) -> list[dict[str, Any]]:
    """What a new coding session pins: each secret's name, host, header and prefix, never its value."""
    return [_pin(row) for row in await _rows(session, project)]


@dataclass
class TurnSecrets:
    secrets: list[HostSecret]
    skipped: list[str]  # why each pinned secret that isn't sent was left out, for the turn's steps

    @property
    def digest(self) -> str:
        """What a warm or sleeping sandbox is matched on: names, hosts and versions (a changed value is a new
        version), never values."""
        return "\n".join(sorted(f"{s.name}={s.entry}:{s.header}:{s.version}" for s in self.secrets))


async def for_turn(
    session: AsyncSession, cipher: Secrets, project: Project, pinned: list[dict[str, Any]] | None, allow: list[str],
) -> TurnSecrets:
    """The session's pinned secrets whose host is unchanged and allowed by the turn's network policy (`allow`), with
    their values as stored now."""
    if not pinned:
        return TurnSecrets([], [])
    rows = {row.name: row for row in await _rows(session, project)}
    entries = network_policy.parse(allow, limit=None)
    secrets: list[HostSecret] = []
    skipped: list[str] = []
    for pin in pinned:
        name = str(pin.get("name") or "")
        row = rows.get(name)
        if row is None:
            skipped.append(f"{name} was deleted")
            continue
        if row.host != pin.get("host") or row.header != pin.get("header") or row.prefix != pin.get("prefix"):
            skipped.append(f"{name} now goes to another host or header: start a new session to use it")
            continue
        entry = network_policy.parse_entry(row.host)
        if not network_policy.permits(entries, entry.host, entry.port):
            skipped.append(f"{name}'s host {row.host} isn't in the network policy any more")
            continue
        value = cipher.decrypt(row.encrypted)
        if value is None:
            skipped.append(f"{name} can't be read with this server's encryption key: save it again")
            continue
        secrets.append(HostSecret(name, entry.host, entry.port, row.header, row.prefix, value, row.version))
    return TurnSecrets(secrets, skipped)


def brief_note(pinned: list[dict[str, Any]] | None) -> str:
    """For Kai's brief on a cloud turn: which variables hold placeholders and how to send them. No values."""
    if not pinned:
        return ""
    lines = [f"- `{p['name']}` for {p['host']}: send it as `{p['header']}: {p['prefix']}${p['name']}`" for p in pinned]
    return ("## Host secrets\nThese environment variables hold placeholders, not the real values: the sandbox's proxy "
            "puts each secret into its header on requests to its host only. Use them where the host expects the "
            "credential (a registry's config, a request header); they work nowhere else, and printing them shows "
            "only the placeholder.\n" + "\n".join(lines))
