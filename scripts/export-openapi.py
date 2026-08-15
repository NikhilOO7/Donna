#!/usr/bin/env python3
"""
Export the OpenAPI schema to a committed file.

FastAPI generates the schema at runtime, so a spec always exists — but only if
the app is running, which makes it useless for client generation in CI, for
reviewing API changes in a diff, and for anyone who wants to see the surface
without booting Postgres.

Committing it makes an API change *visible in code review*: adding, removing or
altering an endpoint shows up as a diff in `openapi.json` next to the code that
caused it. The `--check` mode is the same idea as `alembic check` — it fails
when the committed spec has drifted from the routes.

    uv run python scripts/export-openapi.py            # write it
    uv run python scripts/export-openapi.py --check     # fail if stale (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

OUT = Path(__file__).parent.parent / "openapi.json"


def build() -> dict:
    # Importing main constructs the app (routes, models) without running the
    # lifespan, so no database or Redis connection is needed.
    from apps.api.main import app

    return app.openapi()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed spec is out of date",
    )
    args = ap.parse_args()

    schema = build()
    rendered = json.dumps(schema, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not OUT.exists():
            print(
                f"{OUT.name} is missing — run: uv run python {Path(__file__).name}",
                file=sys.stderr,
            )
            return 1
        if OUT.read_text() != rendered:
            print(
                f"{OUT.name} is out of date. The API surface changed without the "
                f"spec being regenerated.\n"
                f"Run: uv run python scripts/export-openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT.name} is up to date ({len(schema.get('paths', {}))} paths)")
        return 0

    OUT.write_text(rendered)
    paths = schema.get("paths", {})
    ops = sum(len(v) for v in paths.values())
    print(f"wrote {OUT} — {len(paths)} paths, {ops} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
