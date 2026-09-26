"""Outgoing email. Services depend on the EmailSender protocol, never a provider."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Development only: writes emails to the log (links include tokens)."""

    async def send(self, message: EmailMessage) -> None:
        logger.info("email to=%s subject=%s\n%s", message.to, message.subject, message.body)


class OutboxEmailSender:
    """Collects messages in memory. Used by tests."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


def build_email_sender(backend: str) -> EmailSender:
    if backend == "console":
        return ConsoleEmailSender()
    raise ValueError(f"Unknown email backend: {backend}")


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender
