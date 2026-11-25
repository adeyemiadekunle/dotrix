"""Share the API and job worker's Redis transport configuration."""

from urllib.parse import unquote

from arq.connections import RedisSettings

from .settings import Settings


def redis_connection_settings(settings: Settings) -> RedisSettings:
    connection = RedisSettings.from_dsn(settings.redis_url)
    if settings.redis_ca_pem and not connection.ssl:
        raise ValueError("DOTRIX_REDIS_CA_PEM requires a rediss:// URL")
    if connection.ssl:
        # arq leaves the DSN's userinfo percent-encoded.
        if connection.username is not None:
            connection.username = unquote(connection.username)
        if connection.password is not None:
            connection.password = unquote(connection.password)
        connection.ssl_ca_data = settings.redis_ca_pem
        connection.ssl_check_hostname = True
    return connection
