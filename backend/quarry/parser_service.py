"""Credentialless, networkless container entry point, reachable only over a private Unix socket."""

import asyncio
import os
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from quarry.config import settings
from quarry.ingest import subprocess_extract

app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
SLOTS = threading.BoundedSemaphore(2)
BODY_TIMEOUT_SECONDS = 5


@app.get("/health")
def health():
    return {"status": "ready"}


@app.post("/parse")
async def parse(request: Request):
    if not SLOTS.acquire(blocking=False):
        return JSONResponse({"error": "Parser capacity is busy"}, status_code=503)
    try:
        body = bytearray()
        async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
            async for part in request.stream():
                body.extend(part)
                if len(body) > settings().max_upload_bytes:
                    return JSONResponse({"error": "Document exceeds upload limit"}, status_code=413)
        try:
            text = await asyncio.to_thread(
                subprocess_extract,
                bytes(body),
                request.headers.get("content-type", ""),
                request.headers.get("x-document-name", "")[:2048],
            )
            return {"text": text}
        except ValueError as error:
            return {"error": str(error)}
    except TimeoutError:
        return JSONResponse({"error": "Parser input deadline exceeded"}, status_code=408)
    finally:
        SLOTS.release()


def main():
    path = Path("/parser/parse.sock")
    path.unlink(missing_ok=True)
    # Shared only with API/worker containers. No TCP listener, secrets or other volumes.
    os.umask(0o007)
    uvicorn.run(app, uds=str(path), access_log=False, limit_concurrency=4)


if __name__ == "__main__":
    main()
