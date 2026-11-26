import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from dotrix_backend.core.email import EmailMessage, EmailSendError
from dotrix_backend.core.operations import ObservedEmailSender, Operations
from dotrix_backend.modules.agents.streams import RedisRunStreams


async def test_operations_snapshot_exposes_only_aggregate_telemetry() -> None:
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value.__aenter__.return_value = pipe
    timestamp = b"2026-11-25T12:00:00+00:00"
    pipe.execute = AsyncMock(return_value=[
        {b"revision": b"1234567", b"at": timestamp},
        timestamp,
        {
            b"email_retry": b"2", b"email_permanent_failure": b"1",
            b"first_nova_event": b"4", b"first_nova_event_total_ms": b"1200",
        },
    ])
    snapshot = await Operations(redis).snapshot()
    assert snapshot is not None
    assert snapshot.worker_revision == "1234567"
    assert snapshot.worker_heartbeat_at == snapshot.email_last_accepted_at
    assert snapshot.email_retries_today == 2 and snapshot.email_permanent_failures_today == 1
    assert snapshot.first_nova_event_samples_today == 4 and snapshot.first_nova_event_mean_ms_today == 300


async def test_observed_email_preserves_provider_failure_and_records_no_message_content() -> None:
    provider = AsyncMock()
    operations = AsyncMock()
    sender = ObservedEmailSender(provider, operations)
    message = EmailMessage(to="fixtures@example.com", subject="Subject", body="Private message")
    await sender.send(message)
    operations.email_accepted.assert_awaited_once_with()
    provider.send.side_effect = EmailSendError(403, "rejected", retryable=False)
    with pytest.raises(EmailSendError):
        await sender.send(message)
    operations.count.assert_awaited_once_with("email_permanent_failure")


async def test_stream_measures_one_first_event_for_an_observed_nova_attempt() -> None:
    redis = MagicMock()
    redis.pipeline.return_value.execute = AsyncMock()
    redis.publish = AsyncMock()
    redis.set = AsyncMock()
    redis.append = AsyncMock(return_value=5)
    operations = AsyncMock()
    streams = RedisRunStreams(redis, operations=operations)
    stream = await streams.open(uuid.uuid4(), observe_nova=True)
    await stream.publish("")
    operations.first_nova_event.assert_not_called()
    await stream.activity("Working")
    await stream.publish("Hello")
    operations.first_nova_event.assert_awaited_once()

    other_stream = await streams.open(uuid.uuid4())
    await other_stream.publish("Hello")
    operations.first_nova_event.assert_awaited_once()
