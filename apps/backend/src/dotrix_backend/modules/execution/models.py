"""Dispatch intent, committed with the run change that requires execution.

Run status remains in AgentRun/CodingRun. This outbox owns delivery only; an
accepted operation is recovered by its execution runtime, never blindly requeued.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dotrix_backend.db.base import Base, UUIDPrimaryKeyMixin, WorkspaceScopedMixin


class RunDispatch(UUIDPrimaryKeyMixin, WorkspaceScopedMixin, Base):
    __tablename__ = "run_dispatches"
    __table_args__ = (
        CheckConstraint(
            "(agent_run_id IS NOT NULL AND coding_run_id IS NULL) OR "
            "(agent_run_id IS NULL AND coding_run_id IS NOT NULL)",
            name="one_run_target",
        ),
        CheckConstraint("generation > 0", name="positive_generation"),
        UniqueConstraint("agent_run_id", "generation"),
        UniqueConstraint("coding_run_id", "generation"),
        Index("ix_run_dispatches_due", "queue_name", "accepted_at", "discarded_at", "next_attempt_at"),
    )

    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE")
    )
    coding_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("coding_runs.id", ondelete="CASCADE")
    )
    generation: Mapped[int] = mapped_column(Integer)
    queue_name: Mapped[str] = mapped_column(String(128))
    # Private run input, subject to the run's existing workspace/privacy boundary.
    # Redis carries IDs only. Never put credentials or model keys in this payload.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # arq retains terminal result keys, so a failed pre-claim delivery needs a new
    # transport ID. The durable operation ID and its single claim stay unchanged.
    delivery_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set in the same transaction that changes the run to RUNNING.
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A bounded error category, never a raw exception (which can contain secrets).
    last_error: Mapped[str | None] = mapped_column(String(100))
