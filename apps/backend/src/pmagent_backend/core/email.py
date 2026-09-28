"""Outgoing email. Services depend on the EmailSender protocol, never a provider.

Emails are sent from background jobs (`send_email`, see core/jobs.py); a provider error that
may pass (a timeout, 429, 5xx) is raised as retryable so the worker tries again, while one
that won't (a rejected address, a bad key) is not.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import httpx
from fastapi import Request

if TYPE_CHECKING:
    from .settings import Settings

logger = logging.getLogger(__name__)

SEND_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str  # plain text
    html: str | None = None  # the same email as HTML (core/email_templates.py); None: made from body


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class EmailSendError(Exception):
    """The provider didn't accept a message. `retryable`: worth trying again later."""

    def __init__(self, status: int, detail: str, *, retryable: bool) -> None:
        super().__init__(f"email provider answered {status}: {detail}")
        self.status, self.detail, self.retryable = status, detail, retryable


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


class SendlyEmailSender:
    """Sendly (https://developer.sendlyai.com): POST /v1/messages with a bearer key.

    - Plain text only: our emails are short notices with a link.
    - Click tracking off: it would rewrite our links, which carry one-time tokens, through
      the provider's redirector.
    - An Idempotency-Key from the message's content, so a retried job can't send it twice.
    - Nothing from the body is logged (links carry tokens).
    """

    def __init__(
        self,
        api_key: str,
        *,
        from_address: str | None = None,
        base_url: str = "https://api.sendlyai.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.from_address = from_address
        self.base_url = base_url.rstrip("/")
        self._transport = transport  # tests pass a MockTransport

    async def send(self, message: EmailMessage) -> None:
        payload: dict[str, object] = {
            "channel": "email",
            "to": [message.to],
            "subject": message.subject,
            "text": message.body,
            # Sendly's API requires html (despite its docs): the same text, escaped, links clickable.
            "html": message.html or text_to_html(message.body),
            "tracking": False,
        }
        if self.from_address:
            payload["from"] = self.from_address
        idempotency_key = hashlib.sha256(
            f"{message.to}\n{message.subject}\n{message.body}".encode()
        ).hexdigest()
        headers = {"Authorization": f"Bearer {self._api_key}", "Idempotency-Key": idempotency_key}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=SEND_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.post("/v1/messages", json=payload, headers=headers)
        except httpx.TransportError as exc:
            raise EmailSendError(0, f"couldn't reach the provider ({exc.__class__.__name__})", retryable=True) from exc
        if response.status_code >= 400:
            raise EmailSendError(
                response.status_code,
                _error_detail(response),
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        result = _json(response)
        logger.info(
            "email accepted by sendly: id=%s subject=%r skipped=%s",
            result.get("id"),
            message.subject,
            result.get("skipped", 0),
        )


_URL = re.compile(r"https?://[^\s<>\"']+")


def text_to_html(text: str) -> str:
    """A plain-text email as simple HTML: escaped, paragraphs and line breaks kept, links
    clickable. Only our own text goes in, but it's escaped all the same."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        escaped = html.escape(block)
        linked = _URL.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', escaped)
        paragraphs.append(f"<p>{linked.replace(chr(10), '<br>')}</p>")
    return "\n".join(paragraphs)


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_detail(response: httpx.Response) -> str:
    body = _json(response)
    error = body.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("code")
    detail = error or body.get("message") or body.get("detail") or response.reason_phrase
    return str(detail)[:300]


def build_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == "sendly":
        assert settings.sendly_api_key is not None  # (settings validation guarantees it)
        return SendlyEmailSender(
            settings.sendly_api_key.get_secret_value(),
            from_address=settings.email_from,
            base_url=settings.sendly_api_url,
        )
    return ConsoleEmailSender()


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender
