"""Fail on stale versioned OpenAPI contracts."""

import json
from pathlib import Path

from quarry.api import app


def main():
    path = Path("openapi.json")
    if json.loads(path.read_text(encoding="utf-8")) != app.openapi():
        raise SystemExit(
            "OpenAPI contract is stale. Regenerate backend/openapi.json and frontend API types."
        )
    print("OpenAPI contract matches the backend")


if __name__ == "__main__":
    main()
