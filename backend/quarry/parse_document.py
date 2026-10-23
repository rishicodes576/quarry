"""Isolated, resource-bounded parser. Accept input on stdin; never open user paths."""

import json
import resource
import sys

from quarry.config import settings
from quarry.ingest import extract


def main():
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    body = sys.stdin.buffer.read(settings().max_upload_bytes + 1)
    try:
        result = {"text": extract(body, sys.argv[1], sys.argv[2])}
    except ValueError as error:
        result = {"error": str(error)[:240]}
    except Exception:
        result = {"error": "Document could not be parsed within its resource limits"}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
