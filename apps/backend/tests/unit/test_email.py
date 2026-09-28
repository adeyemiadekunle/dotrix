"""Sending email through Sendly (mocked HTTP), and choosing the email backend."""
import json

import httpx
import pytest

from pmagent_backend.core.email import (
    ConsoleEmailSender,
    EmailMessage,
    EmailSendError,
    SendlyEmailSender,
    build_email_sender,
)
from pmagent_backend.core.jobs import JobContext
from pmagent_backend.core.settings import Settings
from pmagent_backend.jobs import send_email

MESSAGE = EmailMessage(to="ada@example.com", subject="Reset your pmagent password", body="Reset: http://app.test/reset?token=abc")


def sendly(handler, **kwargs) -> tuple[SendlyEmailSender, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return SendlyEmailSender("sk_test_key", transport=httpx.MockTransport(record), **kwargs), seen


async def test_sends_plain_text_without_click_tracking() -> None:
    sender, seen = sendly(lambda r: httpx.Response(202, json={"id": "m1", "accepted": 1, "skipped": 0, "status": "queued"}),
                          from_address="pmagent <no-reply@pmagent.dev>")
    await sender.send(MESSAGE)
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://api.sendlyai.com/v1/messages"
    assert request.headers["authorization"] == "Bearer sk_test_key"
    assert json.loads(request.content) == {
        "channel": "email",
        "to": ["ada@example.com"],
        "subject": "Reset your pmagent password",
        "text": "Reset: http://app.test/reset?token=abc",
        "tracking": False,  # the link carries a token: never through a click tracker
        "from": "pmagent <no-reply@pmagent.dev>",
    }
    # The same message always carries the same key, so a retried job can't send it twice.
    await sender.send(MESSAGE)
    assert seen[0].headers["idempotency-key"] == seen[1].headers["idempotency-key"]
    other = EmailMessage(to=MESSAGE.to, subject=MESSAGE.subject, body="another token")
    await sender.send(other)
    assert seen[2].headers["idempotency-key"] != seen[0].headers["idempotency-key"]


async def test_no_from_address_means_the_accounts_default() -> None:
    sender, seen = sendly(lambda r: httpx.Response(202, json={"id": "m1"}))
    await sender.send(MESSAGE)
    assert "from" not in json.loads(seen[0].content)


@pytest.mark.parametrize(
    ("status", "retryable"), [(400, False), (401, False), (403, False), (429, True), (500, True), (503, True)]
)
async def test_errors_say_whether_to_retry(status: int, retryable: bool) -> None:
    sender, _ = sendly(lambda r: httpx.Response(status, json={"error": {"message": "Missing scope messages:send"}}))
    with pytest.raises(EmailSendError) as info:
        await sender.send(MESSAGE)
    assert info.value.status == status and info.value.retryable is retryable
    assert info.value.detail == "Missing scope messages:send"


async def test_unreachable_provider_is_retryable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    sender, _ = sendly(fail)
    with pytest.raises(EmailSendError) as info:
        await sender.send(MESSAGE)
    assert info.value.retryable


async def test_the_email_job_drops_permanent_failures_and_retries_the_rest(caplog) -> None:
    class Failing:
        def __init__(self, retryable: bool) -> None:
            self.retryable = retryable

        async def send(self, message: EmailMessage) -> None:
            raise EmailSendError(400 if not self.retryable else 503, "nope", retryable=self.retryable)

    def ctx(email) -> JobContext:
        return JobContext(session_factory=None, settings=None, email=email)  # type: ignore[arg-type]

    await send_email(ctx(Failing(retryable=False)), to="a@example.com", subject="s", body="token-abc")
    assert "email not sent (400)" in caplog.text and "token-abc" not in caplog.text  # no body in logs
    with pytest.raises(EmailSendError):
        await send_email(ctx(Failing(retryable=True)), to="a@example.com", subject="s", body="b")


def _settings(**values) -> Settings:
    return Settings(database_url="postgresql+asyncpg://localhost/unused",
                    jwt_secret="test-only-jwt-secret-not-used-anywhere-else", **values)  # type: ignore[arg-type]


def test_the_backend_follows_the_key(monkeypatch) -> None:
    for name in ("PMAGENT_SENDLY_API_KEY", "SENDLY_API_KEY", "SENDLY_EMAIL", "PMAGENT_EMAIL_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    assert _settings().email_backend == "console"
    assert isinstance(build_email_sender(_settings()), ConsoleEmailSender)
    monkeypatch.setenv("SENDLY_Email", "sk_test_from_env")  # the name in this project's .env
    with_key = _settings()
    assert with_key.email_backend == "sendly"
    assert isinstance(build_email_sender(with_key), SendlyEmailSender)
    assert _settings(email_backend="console").email_backend == "console"  # can still be forced off
    monkeypatch.delenv("SENDLY_Email")
    with pytest.raises(ValueError, match="needs PMAGENT_SENDLY_API_KEY"):
        _settings(email_backend="sendly")
