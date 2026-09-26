"""Write the OpenAPI schema to packages/api-client/openapi.json.

Run with `pnpm openapi` (which also regenerates the TypeScript client). CI fails
if the committed schema is out of date, so the client always matches the API.
Needs no database or secrets: the app is built with placeholder settings and
never started.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pmagent_backend.core.settings import Settings
from pmagent_backend.main import create_app

OUT = Path(__file__).resolve().parents[3] / "packages" / "api-client" / "openapi.json"


def main() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://localhost/unused",
        jwt_secret="placeholder-secret-for-schema-export-only",  # type: ignore[arg-type]
        docs_enabled=True,
        log_json=False,
    )
    schema = create_app(settings).openapi()
    # Bytes, so Windows doesn't write CRLF and the committed file stays byte-identical.
    OUT.write_bytes((json.dumps(schema, indent=2) + "\n").encode("utf-8"))
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
