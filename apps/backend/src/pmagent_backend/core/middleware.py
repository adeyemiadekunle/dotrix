"""Request context: request ID, access log, and the last-resort 500 handler.

Runs as pure ASGI middleware so it wraps routing, exception handlers, and
other middleware. It binds a request ID (from X-Request-ID, or generated),
echoes it on every response, and writes one access log line per request.
Unhandled exceptions are caught here rather than in a FastAPI exception
handler, because Starlette runs those outside user middleware, where the
request ID is already gone.
"""
from __future__ import annotations

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import problem
from .logging import request_id_var

REQUEST_ID_HEADER = "x-request-id"

access_logger = logging.getLogger("pmagent.access")
logger = logging.getLogger(__name__)

# Paths whose last segment is a secret (calendar feeds: a calendar app can only send a URL).
_SECRET_PATHS = ("/v1/calendar/",)


def loggable_path(path: str) -> str:
    for prefix in _SECRET_PATHS:
        if path.startswith(prefix):
            return f"{prefix}[secret]"
    return path


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode())
        request_id = incoming.decode()[:128] if incoming else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                status, started = message["status"], True
                message.setdefault("headers", []).append(
                    (REQUEST_ID_HEADER.encode(), request_id.encode())
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # Log the traceback; never leak internals to the client.
            logger.exception("unhandled error")
            if started:
                raise
            await problem(500, "internal_error", "Internal server error")(
                scope, receive, send_with_id
            )
        finally:
            path = loggable_path(scope["path"])
            access_logger.info(
                "%s %s %s",
                scope["method"],
                path,
                status,
                extra={
                    "fields": {
                        "method": scope["method"],
                        "path": path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    }
                },
            )
            request_id_var.reset(token)
