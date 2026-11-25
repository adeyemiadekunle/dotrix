import pytest

from dotrix_backend.core.redis import redis_connection_settings
from dotrix_backend.core.settings import Settings


def test_redis_tls_checks_the_hostname_and_uses_the_provider_ca() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/dotrix",
        jwt_secret="test-signing-key-for-redis-settings-verification",
        redis_url="rediss://default:password%40example@redis.example.com:12345/0",
        redis_ca_pem="staging CA bundle",
    )
    connection = redis_connection_settings(settings)
    assert connection.host == "redis.example.com" and connection.port == 12345
    assert connection.password == "password@example"
    assert connection.ssl and connection.ssl_check_hostname
    assert connection.ssl_cert_reqs == "required"
    assert connection.ssl_ca_data == settings.redis_ca_pem


def test_local_redis_uses_plain_tcp_and_preserves_the_database() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/dotrix",
        jwt_secret="test-signing-key-for-redis-settings-verification",
        redis_url="redis://127.0.0.1:6379/2",
    )
    connection = redis_connection_settings(settings)
    assert not connection.ssl
    assert connection.database == 2
    with pytest.raises(ValueError, match="requires a rediss:// URL"):
        redis_connection_settings(settings.model_copy(update={"redis_ca_pem": "staging CA bundle"}))
