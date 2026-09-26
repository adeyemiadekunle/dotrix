"""OpenAPI documentation: overview, tags, error responses, operation IDs.

Served at /docs (Swagger UI), /redoc, and /openapi.json. The exported schema
(`pnpm openapi`) is the contract `packages/api-client` is generated from, so
keep operation IDs stable: they become the client's method names.
"""
from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

DESCRIPTION = """
The pmagent platform API. The web app, desktop app, and `pmagent` CLI are all clients of it.

## Authentication

Send a bearer token in the `Authorization` header. Two kinds are accepted:

| Token | How to get it | Lifetime |
| --- | --- | --- |
| **Access token** (JWT) | `POST /v1/auth/login` or `/v1/auth/signup`; renew with `/v1/auth/refresh` | 15 minutes |
| **API token** (`pmat_…`) | CLI device login (`/v1/auth/device/*`) or `POST /v1/me/tokens` | Up to 1 year |

API tokens act as their user within that user's workspace roles, narrowed by scopes: a
`read`-only token can only make `GET` requests. API tokens can't create more credentials.

To try the API here: sign up or log in, copy `access_token`, click **Authorize**, and paste it.

## Workspaces and permissions

Most routes are scoped to a workspace (`/v1/workspaces/{workspace_id}/…`). What you can do
depends on your role there (owner, admin, member, guest). If you're not a member, the
workspace is reported as **404 Not Found**, never 403, so IDs can't be probed.

## Errors

Errors use [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) `application/problem+json`.
Switch on `type` (for example `…/problems/invalid_link`), not on `detail`, which is for humans.
Every response carries an `X-Request-ID` header; include it when reporting a problem.

## Secrets in requests

One-time tokens (email links, invites, device codes) always travel in request **bodies**,
never in URL paths, so they don't end up in logs.
"""

TAGS: list[dict[str, str]] = [
    {"name": "auth", "description": "Sign-up, login, token refresh, email verification, password reset."},
    {
        "name": "device login",
        "description": "Sign in the CLI and other tools (OAuth 2.0 device authorization grant, "
        "RFC 8628). The tool calls `/code` and polls `/token`; the user approves in the web app.",
    },
    {"name": "api tokens", "description": "Your personal API tokens: create, list, revoke."},
    {"name": "workspaces", "description": "Workspaces, members, roles, and ownership transfer."},
    {"name": "invites", "description": "Invite people by email or shareable link; accept invites."},
    {"name": "projects", "description": "Projects: start from a new repo, an existing repo, or docs only."},
    {
        "name": "knowledge",
        "description": "A project's `.pmagent/` source of truth: files with full version history "
        "(who wrote, instructed, and approved each change), restore, sync for local mirrors, "
        "and Markdown export. Agents may only write the folders their role owns.",
    },
    {
        "name": "documents",
        "description": "Upload PDFs, Office files, and more. Originals are kept; agents read the "
        "markdown conversion under `docs/normalized/` in the project's knowledge.",
    },
    {"name": "issues", "description": "Jira-style issues, board, backlog, sprints. *Coming soon.*"},
    {"name": "approvals", "description": "Action Mode approvals and the audit log. *Coming soon.*"},
    {"name": "health", "description": "Liveness and readiness probes."},
]


class ProblemDetail(BaseModel):
    """RFC 9457 problem details. Every error response has this shape."""

    type: str = Field(examples=["https://pmagent.dev/problems/not_found"])
    title: str = Field(examples=["Not Found"])
    status: int = Field(examples=[404])
    detail: str = Field(examples=["Workspace not found"])
    request_id: str | None = Field(default=None, examples=["3f2b9c0e8a4d4e8f9b1c2d3e4f5a6b7c"])
    errors: list[dict[str, Any]] | None = Field(
        default=None, description="Field errors; only on 422 validation errors."
    )


_ERROR_DESCRIPTIONS = {
    400: "Bad request, for example an invalid or expired link or code",
    401: "Missing, invalid, or expired credentials",
    403: "Signed in, but your role or token scope doesn't allow this",
    404: "Not found, or not visible to you",
    409: "Conflicts with the current state",
    422: "Request body or parameters failed validation",
    503: "A dependency (such as file storage) is unavailable or not configured",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` entries documenting problem+json errors, e.g. `errors(401, 404)`."""
    return {
        code: {"model": ProblemDetail, "description": _ERROR_DESCRIPTIONS.get(code, HTTPStatus(code).phrase)}
        for code in codes
    }


def operation_id(route: APIRoute) -> str:
    """Stable, readable IDs: the route function's name, e.g. `list_workspaces`."""
    return route.name


def install_openapi(app: FastAPI, version: str) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=version,
            description=DESCRIPTION,
            routes=app.routes,
            tags=TAGS,
        )
        # Errors are problem+json, and our 422 body is a ProblemDetail, not FastAPI's default.
        for path in schema["paths"].values():
            for operation in path.values():
                for status, response in operation.get("responses", {}).items():
                    if not status.startswith(("4", "5")):
                        continue
                    response["content"] = {
                        "application/problem+json": {
                            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
                        }
                    }
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.setdefault(
            "ProblemDetail",
            ProblemDetail.model_json_schema(ref_template="#/components/schemas/{model}"),
        )
        for unused in ("HTTPValidationError", "ValidationError"):
            components.pop(unused, None)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
