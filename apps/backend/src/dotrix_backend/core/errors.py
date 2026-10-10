"""Domain exceptions and their single mapping to HTTP responses.

Services raise these; they never import FastAPI. Responses follow RFC 9457
(application/problem+json) and carry the request ID for support and tracing.
Unhandled exceptions are turned into a 500 by RequestContextMiddleware.
"""
from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import request_id_var


class DomainError(Exception):
    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "bad_request"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or HTTPStatus(self.status_code).phrase)
        self.detail = detail or HTTPStatus(self.status_code).phrase


class Unauthorized(DomainError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "unauthorized"


class Forbidden(DomainError):
    status_code = HTTPStatus.FORBIDDEN
    code = "forbidden"


class NotFound(DomainError):
    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"


class Conflict(DomainError):
    status_code = HTTPStatus.CONFLICT
    code = "conflict"


class Unprocessable(DomainError):
    """Well-formed request that breaks a domain rule (bad path, file too large, ...)."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "unprocessable"


class TooManyRequests(DomainError):
    """A rate limit was hit. The response says when to try again (Retry-After, in seconds)."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limited"

    def __init__(self, detail: str, retry_after: float) -> None:
        super().__init__(detail)
        self.retry_after = max(1, int(retry_after + 0.999))


class InvalidLink(DomainError):
    """An emailed or shared token (verification, reset, invite) is unknown, used, or expired."""

    code = "invalid_link"

    def __init__(self) -> None:
        super().__init__("This link is invalid or has expired")


def problem(
    status: int, code: str, detail: str, headers: dict[str, str] | None = None, **extra: object
) -> JSONResponse:
    body = {
        "type": f"https://dotrix.app/problems/{code}",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "request_id": request_id_var.get(),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        if isinstance(exc, TooManyRequests):
            return problem(exc.status_code, exc.code, exc.detail, headers={"Retry-After": str(exc.retry_after)})
        return problem(exc.status_code, exc.code, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, HTTPStatus(exc.status_code).name.lower(), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem(422, "validation_error", "Request validation failed", errors=errors)
