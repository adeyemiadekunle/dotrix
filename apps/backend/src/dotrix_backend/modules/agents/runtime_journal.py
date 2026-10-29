"""Lease-fenced, encrypted journal records for a single bound fx run.

The journal is opaque to Dotrix. A session binding identifies one run and its
runtime configuration; the run row serializes journal updates with lease changes.
This store does not itself schedule agents or authorize replay of tool effects.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dotrix_backend.core.crypto import Secrets
from dotrix_backend.core.errors import Conflict, Forbidden, Unprocessable
from dotrix_engine.runtimes.contracts import RuntimeJournalSnapshot, validate_session

from .models import AgentRun, AgentRuntimeBinding, AgentRuntimeCheckpoint, AgentRuntimeJournal
from .runtime_sessions import RuntimeIdentity, admit_runtime_run
from .storage_backend import SessionFactory

MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 8 * 1024 * 1024
MAX_JOURNAL_BYTES = 8 * 1024 * 1024


class JournalFenced(Conflict):
    """A different writer advanced the journal after this writer loaded it."""

    code = "runtime_journal_fenced"


def _cursor(value: str | None, *, nullable: bool) -> int:
    if value is None and nullable:
        return 0
    if (not isinstance(value, str) or len(value) > 19 or not value.isascii()
            or not value.isdecimal() or value.startswith("0")):
        raise Unprocessable("Invalid runtime journal cursor")
    number = int(value)
    if not 1 <= number < 2**63:
        raise Unprocessable("Invalid runtime journal cursor")
    return number


def _encrypt(secrets: Secrets, data: bytes) -> str:
    return secrets.encrypt(base64.b64encode(data).decode("ascii"))


def _decrypt(secrets: Secrets, encrypted: str, size: int) -> bytes:
    plain = secrets.decrypt(encrypted)
    if plain is None:
        raise Conflict("The runtime journal cannot be decrypted with the configured keys")
    try:
        data = base64.b64decode(plain, validate=True)
    except (ValueError, binascii.Error):
        raise Conflict("The runtime journal is invalid") from None
    if len(data) != size:
        raise Conflict("The runtime journal is invalid")
    return data


class RuntimeJournal:
    def __init__(self, sessions: SessionFactory, secrets: Secrets, *, workspace_id: uuid.UUID, run_id: uuid.UUID,
                 token: int, session_id: str, identity: RuntimeIdentity):
        if identity.runtime != "fx":
            raise ValueError("This journal is for fx sessions")
        validate_session(session_id, "journal")
        self.sessions, self.secrets = sessions, secrets
        self.workspace_id, self.run_id, self.token = workspace_id, run_id, token
        self.session_id, self.identity = session_id, identity

    async def _binding(self, session: AsyncSession) -> tuple[AgentRun, AgentRuntimeBinding]:
        run = await admit_runtime_run(session, self.workspace_id, self.run_id, self.token)
        binding = await session.scalar(select(AgentRuntimeBinding).where(
            AgentRuntimeBinding.workspace_id == self.workspace_id, AgentRuntimeBinding.run_id == self.run_id,
        ).with_for_update())
        if (binding is None or binding.session_id != self.session_id or binding.runtime != self.identity.runtime
                or binding.runtime_version != self.identity.version or binding.config_digest != self.identity.config_digest):
            raise Forbidden("The runtime journal is not bound to this run and configuration")
        return run, binding

    @staticmethod
    def _lease(run: AgentRun) -> None:
        if run.lease_expires_at is None or run.lease_expires_at <= datetime.now(UTC):
            raise Conflict("The run no longer owns this work")

    async def load(self) -> RuntimeJournalSnapshot:
        async with self.sessions() as session:
            run, binding = await self._binding(session)
            checkpoint = await session.scalar(select(AgentRuntimeCheckpoint).where(
                AgentRuntimeCheckpoint.workspace_id == self.workspace_id, AgentRuntimeCheckpoint.binding_id == binding.id,
            ))
            start = checkpoint.through if checkpoint else 0
            rows = list(await session.scalars(select(AgentRuntimeJournal).where(
                AgentRuntimeJournal.workspace_id == self.workspace_id, AgentRuntimeJournal.binding_id == binding.id,
                AgentRuntimeJournal.sequence > start,
            ).order_by(AgentRuntimeJournal.sequence)))
            records = []
            for row in rows:
                if row.sequence != start + 1:
                    raise Conflict("The runtime journal has a missing record")
                start = row.sequence
                records.append((str(row.sequence), _decrypt(self.secrets, row.encrypted, row.byte_count)))
            saved = ((str(checkpoint.through), _decrypt(self.secrets, checkpoint.encrypted, checkpoint.byte_count))
                     if checkpoint else None)
            self._lease(run)
            return RuntimeJournalSnapshot(saved, tuple(records))

    async def append(self, *, expected: str | None, idempotency_key: str, data: bytes) -> str:
        cursor = _cursor(expected, nullable=True)
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
            raise Unprocessable("Invalid runtime journal idempotency key")
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_RECORD_BYTES:
            raise Unprocessable("Invalid runtime journal record size")
        async with self.sessions() as session:
            run, binding = await self._binding(session)
            existing = await session.scalar(select(AgentRuntimeJournal).where(
                AgentRuntimeJournal.workspace_id == self.workspace_id, AgentRuntimeJournal.binding_id == binding.id,
                AgentRuntimeJournal.idempotency_key == idempotency_key,
            ))
            if existing:
                if (existing.expected_sequence != cursor or existing.byte_count != len(data)
                        or not hmac.compare_digest(_decrypt(self.secrets, existing.encrypted, existing.byte_count), data)):
                    raise Conflict("The runtime journal idempotency key was reused for another record")
                self._lease(run)
                return str(existing.sequence)
            head, total = (await session.execute(select(
                func.coalesce(func.max(AgentRuntimeJournal.sequence), 0),
                func.coalesce(func.sum(AgentRuntimeJournal.byte_count), 0),
            ).where(AgentRuntimeJournal.workspace_id == self.workspace_id,
                    AgentRuntimeJournal.binding_id == binding.id))).one()
            if cursor != head or head >= 2**63 - 1:
                raise JournalFenced("The runtime journal has advanced")
            checkpoint_bytes = await session.scalar(select(AgentRuntimeCheckpoint.byte_count).where(
                AgentRuntimeCheckpoint.workspace_id == self.workspace_id, AgentRuntimeCheckpoint.binding_id == binding.id,
            )) or 0
            if total + checkpoint_bytes + len(data) > MAX_JOURNAL_BYTES:
                raise Unprocessable("The runtime journal has reached its size limit")
            record = AgentRuntimeJournal(workspace_id=self.workspace_id, binding_id=binding.id, sequence=head + 1,
                                         expected_sequence=cursor, idempotency_key=idempotency_key,
                                         encrypted=_encrypt(self.secrets, data),
                                         byte_count=len(data), created_at=datetime.now(UTC))
            session.add(record)
            self._lease(run)
            await session.commit()
            return str(record.sequence)

    async def save_checkpoint(self, *, through: str, data: bytes) -> None:
        cursor = _cursor(through, nullable=False)
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_CHECKPOINT_BYTES:
            raise Unprocessable("Invalid runtime checkpoint size")
        async with self.sessions() as session:
            run, binding = await self._binding(session)
            checkpoint = await session.scalar(select(AgentRuntimeCheckpoint).where(
                AgentRuntimeCheckpoint.workspace_id == self.workspace_id, AgentRuntimeCheckpoint.binding_id == binding.id,
            ))
            if checkpoint and cursor <= checkpoint.through:
                if (cursor == checkpoint.through and len(data) == checkpoint.byte_count
                        and hmac.compare_digest(_decrypt(self.secrets, checkpoint.encrypted, checkpoint.byte_count), data)):
                    self._lease(run)
                    return
                raise JournalFenced("The runtime checkpoint has advanced")
            head, total = (await session.execute(select(
                func.coalesce(func.max(AgentRuntimeJournal.sequence), 0),
                func.coalesce(func.sum(AgentRuntimeJournal.byte_count), 0),
            ).where(AgentRuntimeJournal.workspace_id == self.workspace_id,
                    AgentRuntimeJournal.binding_id == binding.id))).one()
            if cursor > head or total + len(data) > MAX_JOURNAL_BYTES:
                raise Unprocessable("Invalid runtime checkpoint cursor or size")
            encrypted = _encrypt(self.secrets, data)
            if checkpoint is None:
                checkpoint = AgentRuntimeCheckpoint(workspace_id=self.workspace_id, binding_id=binding.id,
                                                    through=cursor, encrypted=encrypted,
                                                    byte_count=len(data), created_at=datetime.now(UTC))
                session.add(checkpoint)
            else:
                checkpoint.through, checkpoint.encrypted = cursor, encrypted
                checkpoint.byte_count, checkpoint.created_at = len(data), datetime.now(UTC)
            self._lease(run)
            await session.commit()
