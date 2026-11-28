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

A workspace's owners and admins can keep a secret once as a shared secret (`coding_shared_secrets`); a project uses it
only by referencing it by name (a `shared` project secret), and then gets its host, header and current value when a
turn runs, so rotating it once reaches every project that references it. A project's own secret and its reference
to a shared one can each be setup-only (`phase: setup`): the sandbox's proxy has it only while the environment's setup
script runs, and it's removed (the Docker secret deleted, the OpenShell provider detached) before Kai starts; a turn
whose removal fails stops there.

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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
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
from .models import CodingSecret, CodingSharedSecret

MAX_SECRETS = 20
MAX_SHARED = 50
MAX_VALUE = 8192
_HEADER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
# Headers a proxy must not be asked to write: they'd change where or how the request goes.
_FORBIDDEN_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer",
                                "proxy-authorization", "proxy-connection", "keep-alive", "cookie", "set-cookie"})
DEFAULT_HEADER, DEFAULT_PREFIX = "Authorization", "Bearer "
Phase = Literal["all", "setup"]


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


def _check_header(value: str) -> str:
    if not _HEADER.fullmatch(value) or value.lower() in _FORBIDDEN_HEADERS:
        raise ValueError(f"{value!r} can't carry a secret; use Authorization or the header the service documents")
    return value


def _check_prefix(value: str) -> str:
    if len(value) > 32 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("The prefix must be printable text such as `Bearer `, at most 32 characters")
    return value


def _check_value(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or len(value) > MAX_VALUE or any(c in value for c in "\x00\r\n"):
        raise ValueError(f"The value must be one line of 1 to {MAX_VALUE} characters")
    return value


class SharedSecretSave(BaseModel):
    """A workspace's shared secret: the same fields as a project's own."""

    model_config = ConfigDict(extra="forbid")
    host: str = Field(description="The one host (`api.example.com` or `host:port`) the value is sent to; within the "
                                  "workspace's network limit when it has one")
    header: str = Field(default=DEFAULT_HEADER, description="The request header the value goes in")
    prefix: str = Field(default=DEFAULT_PREFIX, description="What comes before the value in the header")
    value: str | None = Field(default=None, description=(
        "The secret. Required for a new secret; leave it out to keep the stored one. Never returned"))

    @field_validator("host")
    @classmethod
    def _host(cls, value: str) -> str:
        return check_host(value)

    @field_validator("header")
    @classmethod
    def _header(cls, value: str) -> str:
        return _check_header(value)

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        return _check_prefix(value)

    @field_validator("value")
    @classmethod
    def _value(cls, value: str | None) -> str | None:
        return _check_value(value)


class CodingSecretSave(BaseModel):
    """A project's secret: its own (host, header, prefix, value), or `shared`, a reference by name to the workspace's
    shared secret of the same name, which brings its own host, header and value."""

    model_config = ConfigDict(extra="forbid")
    shared: bool = Field(default=False, description="Reference the workspace's shared secret of this name instead of "
                                                    "keeping a value here; host, header, prefix and value are then left out")
    phase: Phase = Field(default="all", description=(
        "`all`: the setup script and Kai's commands. `setup`: the setup script only; removed before Kai runs"))
    host: str | None = Field(default=None, description="The one host (`api.example.com` or `host:port`) the value is "
                                                       "sent to; it must be in the project's network policy")
    header: str | None = Field(default=None, description="The request header the value goes in (Authorization)")
    prefix: str | None = Field(default=None, description="What comes before the value in the header (`Bearer `)")
    value: str | None = Field(default=None, description=(
        "The secret. Required for a new secret of the project's own; leave it out to keep the stored one. Never "
        "returned"))

    @field_validator("host")
    @classmethod
    def _host(cls, value: str | None) -> str | None:
        return None if value is None else check_host(value)

    @field_validator("header")
    @classmethod
    def _header(cls, value: str | None) -> str | None:
        return None if value is None else _check_header(value)

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str | None) -> str | None:
        return None if value is None else _check_prefix(value)

    @field_validator("value")
    @classmethod
    def _value(cls, value: str | None) -> str | None:
        return _check_value(value)

    @model_validator(mode="after")
    def _shape(self) -> CodingSecretSave:
        if self.shared and any(v is not None for v in (self.host, self.header, self.prefix, self.value)):
            raise ValueError("A workspace secret brings its own host, header and value: leave them out")
        if not self.shared and self.host is None:
            raise ValueError("A secret needs its host")
        return self


class CodingSecretRead(BaseModel):
    """A project's secret without its value. For a reference to a shared secret, the shared secret's host and header;
    `missing` when the workspace no longer has it."""

    name: str
    shared: bool = False
    phase: Phase = "all"
    host: str | None
    header: str | None
    prefix: str | None
    version: int
    allowed: bool = Field(description="Whether the project's network policy allows its host now; a secret whose "
                                      "host isn't allowed isn't sent")
    missing: bool = Field(default=False, description="A reference to a shared secret the workspace no longer has")
    updated_at: datetime
    updated_by_id: uuid.UUID | None


class SharedSecretRead(BaseModel):
    """A workspace's shared secret without its value."""

    name: str
    host: str
    header: str
    prefix: str
    version: int
    projects: int = Field(description="How many of the workspace's projects reference it")
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
    version: int | str
    phase: str = "all"

    def __repr__(self) -> str:  # never the value
        return f"HostSecret({self.name}, {self.host}:{self.port}, {self.phase})"

    @property
    def entry(self) -> str:
        return self.host if self.port == network_policy.DEFAULT_PORT else f"{self.host}:{self.port}"

    @property
    def placeholder(self) -> str:
        """OpenShell's placeholder; Docker Cloud gives its own when the secret is stored."""
        return f"openshell:resolve:env:{self.name}"


@dataclass(frozen=True)
class _Resolved:
    host: str
    header: str
    prefix: str
    encrypted: str
    version: int | str


def _resolve(row: CodingSecret, shared: dict[str, CodingSharedSecret]) -> _Resolved | None:
    """A project secret's host, header, prefix, value and version: its own, or its shared secret's (None if gone)."""
    if not row.shared:
        return _Resolved(row.host or "", row.header or DEFAULT_HEADER, row.prefix if row.prefix is not None else
                         DEFAULT_PREFIX, row.encrypted or "", row.version)
    found = shared.get(row.name)
    if found is None:
        return None
    return _Resolved(found.host, found.header, found.prefix, found.encrypted, f"{row.version}.{found.version}")


def _host_allowed(host: str, allow: list[str]) -> bool:
    entry = network_policy.parse_entry(host)
    return network_policy.permits(network_policy.parse(allow, limit=None), entry.host, entry.port)


def _read(row: CodingSecret, resolved: _Resolved | None, allow: list[str]) -> CodingSecretRead:
    return CodingSecretRead(
        name=row.name, shared=row.shared, phase=row.phase,  # type: ignore[arg-type]
        host=resolved.host if resolved else None, header=resolved.header if resolved else None,
        prefix=resolved.prefix if resolved else None, version=row.version,
        allowed=resolved is not None and _host_allowed(resolved.host, allow), missing=resolved is None,
        updated_at=row.updated_at, updated_by_id=row.updated_by_id)


async def _rows(session: AsyncSession, project: Project) -> list[CodingSecret]:
    return list((await session.scalars(select(CodingSecret).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id,
    ).order_by(CodingSecret.name))).all())


async def _shared_rows(session: AsyncSession, workspace_id: uuid.UUID, names: list[str] | None = None,
                       ) -> dict[str, CodingSharedSecret]:
    query = select(CodingSharedSecret).where(CodingSharedSecret.workspace_id == workspace_id)
    if names is not None:
        query = query.where(CodingSharedSecret.name.in_(names))
    return {row.name: row for row in (await session.scalars(query)).all()}


async def secret_names(session: AsyncSession, project: Project) -> set[str]:
    return set((await session.scalars(select(CodingSecret.name).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id))).all())


async def _allowed(session: AsyncSession, project: Project) -> list[str]:
    from .network import allowed_hosts

    await session.refresh(project, ["sandbox_network"])
    return allowed_hosts(await session.get(Workspace, project.workspace_id), project)


async def list_secrets(session: AsyncSession, project: Project) -> list[CodingSecretRead]:
    allow = await _allowed(session, project)
    rows = await _rows(session, project)
    shared = await _shared_rows(session, project.workspace_id, [r.name for r in rows if r.shared])
    return [_read(row, _resolve(row, shared), allow) for row in rows]


async def save_secret(
    session: AsyncSession, cipher: Secrets, member: Membership, project: Project, name: str, data: CodingSecretSave,
) -> CodingSecretRead:
    """Add or change a project's secret, its own or a reference to a shared one. 409 when its host isn't in the
    project's network policy, the workspace has no shared secret of that name, its name is one of the environment's
    variables, or the project has its maximum; a new secret of its own needs a value."""
    from .environments import profile

    try:
        check_name(name)
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    allow = await _allowed(session, project)
    shared = await _shared_rows(session, project.workspace_id, [name]) if data.shared else {}
    if data.shared and name not in shared:
        raise Conflict(f"This workspace has no workspace secret named {name}")
    host = shared[name].host if data.shared else data.host
    assert host is not None
    if not _host_allowed(host, allow):
        raise Conflict(f"{host} isn't in this project's network access: allow it there first")
    if name in profile(project.coding_environment).variables:
        raise Conflict(f"{name} is one of the environment's variables; remove it there or choose another name")
    row = await session.scalar(select(CodingSecret).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id,
        CodingSecret.name == name).with_for_update())
    now = datetime.now(UTC)
    created = row is None
    if row is None:
        if not data.shared and data.value is None:
            raise Conflict("A new secret needs its value")
        if len(await secret_names(session, project)) >= MAX_SECRETS:
            raise Conflict(f"A project has at most {MAX_SECRETS} secrets")
        row = CodingSecret(workspace_id=project.workspace_id, project_id=project.id, name=name, version=1,
                           created_at=now)
        session.add(row)
    else:
        if not data.shared and row.shared and data.value is None:
            raise Conflict("Give the secret its own value: until now it used a workspace secret")
        row.version += 1
    row.shared, row.phase = data.shared, data.phase
    if data.shared:
        row.host = row.header = row.prefix = row.encrypted = None
    else:
        row.host = data.host
        row.header = data.header or DEFAULT_HEADER
        row.prefix = data.prefix if data.prefix is not None else DEFAULT_PREFIX
        if data.value is not None:
            row.encrypted = cipher.encrypt(data.value)
    row.updated_by_id, row.updated_at = member.user_id, now
    await session.flush()
    AuditLog(session).record(
        workspace_id=project.workspace_id, project_id=project.id,
        action="coding_secret.created" if created else "coding_secret.updated", target=name,
        actor_type=AuthorType.USER, actor_user_id=member.user_id,
        details={"name": name, "host": host, "shared": row.shared, "phase": row.phase, "version": row.version,
                 "value_changed": data.value is not None})
    await session.commit()
    return _read(row, _resolve(row, shared), allow)


async def delete_secret(session: AsyncSession, member: Membership, project: Project, name: str) -> None:
    row = await session.scalar(select(CodingSecret).where(
        CodingSecret.workspace_id == project.workspace_id, CodingSecret.project_id == project.id,
        CodingSecret.name == name))
    if row is None:
        raise NotFound("No such secret")
    await session.delete(row)
    AuditLog(session).record(
        workspace_id=project.workspace_id, project_id=project.id, action="coding_secret.deleted", target=name,
        actor_type=AuthorType.USER, actor_user_id=member.user_id,
        details={"name": name, "host": row.host, "shared": row.shared})
    await session.commit()


# -- the workspace's shared secrets ------------------------------------------------------------------------------


async def _references(session: AsyncSession, workspace_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in (await session.scalars(select(CodingSecret.name).where(
            CodingSecret.workspace_id == workspace_id, CodingSecret.shared.is_(True)))).all():
        counts[name] = counts.get(name, 0) + 1
    return counts


def _shared_read(row: CodingSharedSecret, projects: int) -> SharedSecretRead:
    return SharedSecretRead(name=row.name, host=row.host, header=row.header, prefix=row.prefix, version=row.version,
                            projects=projects, updated_at=row.updated_at, updated_by_id=row.updated_by_id)


async def list_shared(session: AsyncSession, member: Membership) -> list[SharedSecretRead]:
    references = await _references(session, member.workspace_id)
    rows = sorted((await _shared_rows(session, member.workspace_id)).values(), key=lambda r: r.name)
    return [_shared_read(row, references.get(row.name, 0)) for row in rows]


async def save_shared(
    session: AsyncSession, cipher: Secrets, member: Membership, name: str, data: SharedSecretSave,
) -> SharedSecretRead:
    """Add or change a workspace's shared secret. 409 when its host is outside the workspace's network limit or a new
    one has no value. Projects that reference it get the change on their sessions' next turns (a moved host or header
    is left out of sessions that pinned the old one)."""
    from .network import limit_of

    try:
        check_name(name)
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    limit = limit_of(await session.get(Workspace, member.workspace_id))
    if limit is not None and not network_policy.within(limit, data.host):
        raise Conflict(f"{data.host} is outside the network access limit for all projects")
    row = await session.scalar(select(CodingSharedSecret).where(
        CodingSharedSecret.workspace_id == member.workspace_id, CodingSharedSecret.name == name).with_for_update())
    now = datetime.now(UTC)
    created = row is None
    if row is None:
        if data.value is None:
            raise Conflict("A new secret needs its value")
        if len(await _shared_rows(session, member.workspace_id)) >= MAX_SHARED:
            raise Conflict(f"A workspace has at most {MAX_SHARED} workspace secrets")
        row = CodingSharedSecret(workspace_id=member.workspace_id, name=name, version=1, created_at=now)
        session.add(row)
    else:
        row.version += 1
    row.host, row.header, row.prefix = data.host, data.header, data.prefix
    if data.value is not None:
        row.encrypted = cipher.encrypt(data.value)
    row.updated_by_id, row.updated_at = member.user_id, now
    await session.flush()
    AuditLog(session).record(
        workspace_id=member.workspace_id, action="coding_shared_secret.created" if created
        else "coding_shared_secret.updated", target=name, actor_type=AuthorType.USER, actor_user_id=member.user_id,
        details={"name": name, "host": row.host, "header": row.header, "version": row.version,
                 "value_changed": data.value is not None})
    await session.commit()
    return _shared_read(row, (await _references(session, member.workspace_id)).get(name, 0))


async def delete_shared(session: AsyncSession, member: Membership, name: str) -> None:
    """Delete a shared secret. Projects' references stay (listed as missing) and their turns go on without it."""
    row = await session.scalar(select(CodingSharedSecret).where(
        CodingSharedSecret.workspace_id == member.workspace_id, CodingSharedSecret.name == name))
    if row is None:
        raise NotFound("No such secret")
    await session.delete(row)
    AuditLog(session).record(
        workspace_id=member.workspace_id, action="coding_shared_secret.deleted", target=name,
        actor_type=AuthorType.USER, actor_user_id=member.user_id, details={"name": name, "host": row.host})
    await session.commit()


# -- pinned per session, loaded per turn -------------------------------------------------------------------------


async def project_snapshot(session: AsyncSession, project: Project) -> list[dict[str, Any]]:
    """What a new coding session pins: each secret's name, whether it's shared, its phase, and its host, header and
    prefix as they resolve now; never a value. A reference to a missing shared secret isn't pinned."""
    rows = await _rows(session, project)
    shared = await _shared_rows(session, project.workspace_id, [r.name for r in rows if r.shared])
    pins = []
    for row in rows:
        resolved = _resolve(row, shared)
        if resolved is not None:
            pins.append({"name": row.name, "shared": row.shared, "phase": row.phase, "host": resolved.host,
                         "header": resolved.header, "prefix": resolved.prefix})
    return pins


@dataclass
class TurnSecrets:
    secrets: list[HostSecret]
    skipped: list[str]  # why each pinned secret that isn't sent was left out, for the turn's steps

    @property
    def kai(self) -> list[HostSecret]:
        return [s for s in self.secrets if s.phase != "setup"]

    @property
    def setup_only(self) -> list[HostSecret]:
        return [s for s in self.secrets if s.phase == "setup"]

    @property
    def digest(self) -> str:
        """What a warm or sleeping sandbox is matched on: names, hosts, phases and versions (a changed value is a new
        version), never values."""
        return "\n".join(sorted(f"{s.name}={s.entry}:{s.header}:{s.phase}:{s.version}" for s in self.secrets))

    def without_setup(self) -> TurnSecrets:
        return TurnSecrets(self.kai, self.skipped)


async def for_turn(
    session: AsyncSession, cipher: Secrets, project: Project, pinned: list[dict[str, Any]] | None, allow: list[str],
) -> TurnSecrets:
    """The session's pinned secrets whose host and header are unchanged and allowed by the turn's network policy
    (`allow`), with their values as stored now (a shared one's from the workspace)."""
    if not pinned:
        return TurnSecrets([], [])
    rows = {row.name: row for row in await _rows(session, project)}
    shared = await _shared_rows(session, project.workspace_id, [r.name for r in rows.values() if r.shared])
    secrets: list[HostSecret] = []
    skipped: list[str] = []
    for pin in pinned:
        name = str(pin.get("name") or "")
        row = rows.get(name)
        if row is None or bool(row.shared) != bool(pin.get("shared", False)):
            skipped.append(f"{name} was deleted or replaced: start a new session to use it")
            continue
        resolved = _resolve(row, shared)
        if resolved is None:
            skipped.append(f"{name}'s workspace secret was deleted")
            continue
        if (resolved.host != pin.get("host") or resolved.header != pin.get("header")
                or resolved.prefix != pin.get("prefix")):
            skipped.append(f"{name} now goes to another host or header: start a new session to use it")
            continue
        if not _host_allowed(resolved.host, allow):
            skipped.append(f"{name}'s host {resolved.host} isn't in the network access any more")
            continue
        value = cipher.decrypt(resolved.encrypted) if resolved.encrypted else None
        if value is None:
            skipped.append(f"{name} can't be read with this server's encryption key: save it again")
            continue
        entry = network_policy.parse_entry(resolved.host)
        secrets.append(HostSecret(name, entry.host, entry.port, resolved.header, resolved.prefix, value,
                                  resolved.version, str(pin.get("phase") or "all")))
    return TurnSecrets(secrets, skipped)


def brief_note(pinned: list[dict[str, Any]] | None) -> str:
    """For Kai's brief on a cloud turn: which variables hold placeholders and how to send them. No values, and no
    setup-only secrets (Kai never has them)."""
    pinned = [p for p in pinned or [] if p.get("phase", "all") != "setup"]
    if not pinned:
        return ""
    lines = [f"- `{p['name']}` for {p['host']}: send it as `{p['header']}: {p['prefix']}${p['name']}`" for p in pinned]
    return ("## Host secrets\nThese environment variables hold placeholders, not the real values: the sandbox's proxy "
            "puts each secret into its header on requests to its host only. Use them where the host expects the "
            "credential (a registry's config, a request header); they work nowhere else, and printing them shows "
            "only the placeholder.\n" + "\n".join(lines))
