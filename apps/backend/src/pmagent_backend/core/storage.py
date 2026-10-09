"""Object storage for binary files (document originals). Services depend on the
BlobStorage protocol, never on S3 directly.

- S3BlobStorage: any S3-compatible store. Locally that's MinIO from
  docker-compose; in production AWS S3, Cloudflare R2, etc. Only env vars change.
- MemoryBlobStorage: tests.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Protocol

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Request

from .errors import DomainError, NotFound
from .settings import Settings

logger = logging.getLogger(__name__)


class StorageUnavailable(DomainError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "storage_unavailable"


class BlobStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class S3BlobStorage:
    def __init__(
        self, *, endpoint_url: str, access_key: str, secret_key: str, bucket: str, region: str
    ) -> None:
        self.bucket = bucket
        self._session = aioboto3.Session()
        self._client_args: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
        }
        self._bucket_ready = False

    def _client(self) -> Any:
        return self._session.client("s3", **self._client_args)

    async def _ensure_bucket(self, s3: Any) -> None:
        if self._bucket_ready:
            return
        try:
            await s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            await s3.create_bucket(Bucket=self.bucket)
            logger.info("created storage bucket %s", self.bucket)
        self._bucket_ready = True

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            async with self._client() as s3:
                await self._ensure_bucket(s3)
                await s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("storage put failed")
            raise StorageUnavailable("File storage is unavailable; try again shortly") from exc

    async def get(self, key: str) -> bytes:
        try:
            async with self._client() as s3:
                response = await s3.get_object(Bucket=self.bucket, Key=key)
                async with response["Body"] as body:
                    return await body.read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise NotFound("File not found in storage") from exc
            logger.exception("storage get failed")
            raise StorageUnavailable("File storage is unavailable; try again shortly") from exc
        except BotoCoreError as exc:
            logger.exception("storage get failed")
            raise StorageUnavailable("File storage is unavailable; try again shortly") from exc

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as s3:
                await s3.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError):
            logger.exception("storage delete failed for %s", key)  # best effort


class MemoryBlobStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise NotFound("File not found in storage")
        return self.objects[key][0]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def build_storage(settings: Settings) -> BlobStorage | None:
    if not (settings.s3_endpoint_url and settings.s3_access_key and settings.s3_secret_key):
        return None
    return S3BlobStorage(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
        bucket=settings.s3_bucket,
        region=settings.s3_region,
    )


def optional_storage(request: Request) -> BlobStorage | None:
    """Storage when it's configured: for deletes, which work without it when there are no files."""
    storage: BlobStorage | None = request.app.state.storage
    return storage


def get_storage(request: Request) -> BlobStorage:
    storage: BlobStorage | None = request.app.state.storage
    if storage is None:
        raise StorageUnavailable("File storage isn't configured (set PMAGENT_S3_* in .env)")
    return storage
