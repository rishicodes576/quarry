import asyncio
import io
import json
from unittest.mock import Mock

from fastapi import Request
from fastapi.testclient import TestClient

from quarry import parse_document, parser_service
from quarry.config import settings


def test_parser_service_capacity_size_and_parse_errors(monkeypatch):
    with TestClient(parser_service.app) as client:
        assert client.get("/health").json() == {"status": "ready"}
        parser_service.SLOTS.acquire()
        parser_service.SLOTS.acquire()
        try:
            assert client.post("/parse", content=b"text").status_code == 503
        finally:
            parser_service.SLOTS.release()
            parser_service.SLOTS.release()
        monkeypatch.setattr(settings(), "max_upload_bytes", 8)
        assert client.post("/parse", content=b"x" * 9).status_code == 413
        monkeypatch.setattr(settings(), "max_upload_bytes", 1024)
        value = client.post(
            "/parse", content=b"A small source", headers={"content-type": "text/plain"}
        )
        assert value.json() == {"text": "A small source"}
        value = client.post("/parse", content=b"\xff", headers={"content-type": "text/plain"})
        assert "UTF-8" in value.json()["error"]


def test_parser_input_deadline_releases_capacity(monkeypatch):
    monkeypatch.setattr(parser_service, "BODY_TIMEOUT_SECONDS", 0.02)

    async def scenario():
        async def receive():
            await asyncio.sleep(1)
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(
            {"type": "http", "method": "POST", "path": "/parse", "headers": []}, receive=receive
        )
        assert (await parser_service.parse(request)).status_code == 408
        assert parser_service.SLOTS.acquire(blocking=False)
        assert parser_service.SLOTS.acquire(blocking=False)
        parser_service.SLOTS.release()
        parser_service.SLOTS.release()

    asyncio.run(scenario())


def test_parser_start_removes_stale_socket_and_uses_uds_only(monkeypatch, tmp_path):
    path = tmp_path / "parse.sock"
    path.write_text("inert stale socket")
    monkeypatch.setattr(parser_service, "Path", lambda _: path)
    monkeypatch.setattr(parser_service.os, "umask", Mock())
    run = Mock()
    monkeypatch.setattr(parser_service.uvicorn, "run", run)
    parser_service.main()
    assert not path.exists()
    assert run.call_args.kwargs["uds"] == str(path)
    assert "host" not in run.call_args.kwargs and "port" not in run.call_args.kwargs


def test_bounded_child_error_protocol(monkeypatch):
    # Exercise error serialization without changing the test process's resource limits.
    monkeypatch.setattr(parse_document.resource, "setrlimit", Mock())
    monkeypatch.setattr(parse_document.sys, "argv", ["parser", "text/plain", "source.txt"])
    for error, expected in [
        (ValueError("Invalid source"), "Invalid source"),
        (RuntimeError("sensitive internal detail"), "resource limits"),
    ]:
        monkeypatch.setattr(parse_document, "extract", Mock(side_effect=error))
        monkeypatch.setattr(parse_document.sys, "stdin", Mock(buffer=io.BytesIO(b"source")))
        output = io.StringIO()
        monkeypatch.setattr(parse_document.sys, "stdout", output)
        parse_document.main()
        assert expected in json.loads(output.getvalue())["error"]
        assert "sensitive internal detail" not in output.getvalue()
    monkeypatch.setattr(parse_document, "extract", Mock(return_value="Parsed evidence"))
    monkeypatch.setattr(parse_document.sys, "stdin", Mock(buffer=io.BytesIO(b"source")))
    output = io.StringIO()
    monkeypatch.setattr(parse_document.sys, "stdout", output)
    parse_document.main()
    assert json.loads(output.getvalue()) == {"text": "Parsed evidence"}
