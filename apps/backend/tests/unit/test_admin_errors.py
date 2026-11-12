"""The console's failure key shows a kind of failure, never what the error repeated."""

from __future__ import annotations

import pytest

from dotrix_backend.modules.admin.platform import _failure_key


@pytest.mark.parametrize(
    ("error", "key"),
    [
        ('BadRequestError: Error code: 400 - {"error": {"message": "my secret plan"}}', "BadRequestError: HTTP 400"),
        ("RateLimitError: you exceeded your current quota", "RateLimitError: rate limited"),
        ("ReadTimeout: the request timed out after 60s", "ReadTimeout: timed out"),
        ("ConnectError: could not connect to host", "ConnectError: connection failed"),
        ("AuthenticationError: invalid api key", "AuthenticationError: authentication failed"),
        ("BadRequestError: maximum context length exceeded", "BadRequestError: context too long"),
        ("ValueError: something about my secret plan", "ValueError: other"),
        ("something about my secret plan", "other"),
        ("Stopped by Ada Lovelace", "Stopped by a person"),
        ("Kai didn't finish: the file secret.txt could not be read", "Kai didn't finish"),
        ("The person who asked no longer sees this project", "The person who asked no longer sees this project"),
        ("Stopped: Anthropic refused this run (my plan)", "Stopped"),
        ("The @ada-secret agent no longer exists; pick another agent", "An agent no longer exists"),
        (None, "(no message)"),
        ("", "(no message)"),
        ("  \n ", "(no message)"),
    ],
)
def test_failure_key(error: str | None, key: str) -> None:
    assert _failure_key(error) == key


def test_a_long_line_is_short() -> None:
    assert len(_failure_key("SomeError: " + "x" * 500)) <= 80
    assert len(_failure_key("y" * 500)) <= 80


def test_email_addresses_and_urls_never_appear() -> None:
    key = _failure_key("ProviderError: ada@example.com asked https://example.com/private?q=plan and got refused")
    assert "ada@" not in key and "http" not in key and "example" not in key
