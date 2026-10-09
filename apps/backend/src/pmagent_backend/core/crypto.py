"""Secrets at rest (organisations' model provider keys): Fernet with `PMAGENT_ENCRYPTION_KEY`.

Several keys, comma-separated, rotate: the first encrypts, every one decrypts, and `rotate`
re-encrypts a value under the first. Generate one with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
"""
from __future__ import annotations

from http import HTTPStatus

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .errors import DomainError
from .settings import Settings


class EncryptionNotConfigured(DomainError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "encryption_not_configured"


class Secrets:
    def __init__(self, keys: str | None) -> None:
        parts = [k.strip() for k in (keys or "").split(",") if k.strip()]
        self._fernet = MultiFernet([Fernet(k.encode()) for k in parts]) if parts else None

    @classmethod
    def from_settings(cls, settings: Settings) -> Secrets:
        return cls(settings.encryption_key.get_secret_value() if settings.encryption_key else None)

    @property
    def configured(self) -> bool:
        return self._fernet is not None

    def _need(self) -> MultiFernet:
        if self._fernet is None:
            raise EncryptionNotConfigured(
                "This server can't store keys yet: set PMAGENT_ENCRYPTION_KEY and restart"
            )
        return self._fernet

    def encrypt(self, value: str) -> str:
        return self._need().encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str | None:
        """The value, or None when no key here can read it (a key was removed)."""
        try:
            return self._need().decrypt(token.encode()).decode()
        except InvalidToken:
            return None

    def rotate(self, token: str) -> str:
        return self._need().rotate(token.encode()).decode()
