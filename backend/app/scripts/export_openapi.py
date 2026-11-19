"""Write the API's OpenAPI schema to a file, without a server or a database (DESIGN §7.6).

    uv run python -m app.scripts.export_openapi            # writes frontend/openapi.json
    uv run python -m app.scripts.export_openapi --check    # exit 1 if that file is stale

The frontend generates its TypeScript types from this file (openapi-typescript), so the
committed copy is the API contract. CI runs `--check`: a backend change that alters the
API but forgets to re-export fails the build instead of silently breaking the frontend.

Interview notes:
- The schema comes from the same FastAPI app object that serves requests (routes +
  Pydantic models), so the contract can't drift from the code that implements it.
- Placeholder settings: building the app reads config, but the schema doesn't depend on
  any of it, and nothing connects to the DB until the lifespan runs (it never does here).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.factory import create_app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"

# Not secrets: never used to connect or sign anything, only to satisfy Settings validation.
_PLACEHOLDER_SETTINGS: dict[str, Any] = {
    "environment": "test",
    "database_url": "postgresql://unused:unused@127.0.0.1:1/unused",
    "allowed_origins": "http://localhost:5173",
    "batch_invite_code": "placeholder",
    "cron_secret": "placeholder-not-a-secret",
}


def render_schema() -> str:
    """The OpenAPI schema as stable JSON text (same input → byte-identical output)."""
    app = create_app(Settings(_env_file=None, **_PLACEHOLDER_SETTINGS))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true", help="don't write; exit 1 if the file is out of date"
    )
    args = parser.parse_args(argv)
    output: Path = args.output
    schema = render_schema()

    if args.check:
        current = output.read_text(encoding="utf-8") if output.exists() else None
        if current != schema:
            print(
                f"{output} is out of date. Run: uv run python -m app.scripts.export_openapi",
                file=sys.stderr,
            )
            return 1
        print(f"{output} is up to date.")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(schema, encoding="utf-8", newline="\n")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
